"""M8b/M9 automatic volume executor.

This is the only path from controller decisions to real system volume writes. It is
platform independent; a platform opts in by implementing ``apply_volume_db`` and
``restore_volume`` (lowering, M8b) plus ``raise_volume_db`` (recovery, M9). Every
write is re-checked here, independent of the controller:

* lowering: at most MAX_WRITE_STEP_DB per write and ``maxLowerDbPerSecond`` per
  elapsed second; never below ``minSystemVolume`` and never more than
  ``maxAutoAttenuationDb`` below the session baseline;
* recovery (plan A): at most ``maxRaiseDbPerSecond`` per elapsed second and never
  above the session baseline, i.e. the volume the user chose. It only gives back what
  this program took away;
* the decision must be based on a fresh volume read; stale reads are skipped;
* device switch or user volume change ends the session without restoring;
* platform/COM failures or read-back mismatches disable automatic writes.

On exit, or when the user leaves an automatic mode, the baseline is restored only if
the endpoint still shows the last value this program wrote.
"""

from __future__ import annotations

from copy import deepcopy

EXECUTOR_VERSION = "executor-m9/v1"
MAX_WRITE_STEP_DB = 3.0
MIN_WRITE_INTERVAL_MS = 200.0
STALE_READ_MS = 1000.0
READBACK_TOLERANCE_DB = 0.6
CEILING_TOLERANCE_PERCENT = 0.6


class LowerOnlyExecutor:
    def __init__(self, source):
        self.source = source
        self.session = None
        self.disabled_reason = None
        self.write_count = 0
        self.raise_count = 0
        self.last_result = None

    @staticmethod
    def supported(source):
        return (callable(getattr(source, "apply_volume_db", None))
                and callable(getattr(source, "restore_volume", None)))

    @staticmethod
    def supports_raise(source):
        return LowerOnlyExecutor.supported(source) and callable(
            getattr(source, "raise_volume_db", None))

    def gate(self, observation, mode="lower-only"):
        """Return None when the automatic mode may run, else a human readable reason."""
        if not self.supported(self.source):
            return "当前平台尚未提供自动音量写入"
        if mode == "automatic" and not self.supports_raise(self.source):
            return "当前平台尚未提供自动回升写入"
        if observation is None or not observation.get("captureAvailable"):
            return "当前没有可用的系统音频数据"
        status = observation.get("profileStatus")
        if status != "valid":
            return "设备反馈档案不可用（%s），请先完成三档校准" % status
        if observation.get("captureResponse") not in {"pre-volume", "post-volume"}:
            return "捕获位置未分类"
        if observation.get("captureConfidence") not in {"high", "medium"}:
            return "校准置信度不足"
        if not observation.get("volumeDbMappingReliable"):
            return "设备 dB 映射不可靠"
        if not observation.get("volumeControllable"):
            return "当前设备不可写系统音量"
        if observation.get("systemVolume") is None or observation.get("systemVolumeDb") is None:
            return "无法读取当前系统音量"
        return None

    def begin(self, observation):
        self.disabled_reason = None
        self.session = {
            "deviceId": observation["deviceId"],
            "baselineVolume": observation["systemVolume"],
            "baselineVolumeDb": observation["systemVolumeDb"],
            "lastWrittenVolume": None,
            "lastWrittenVolumeDb": None,
            "lastWriteAtMs": None,
            "writes": 0,
            "raises": 0,
        }

    def interrupt(self, reason):
        """User override or device change: forget the session, never restore over it."""
        dropped = self.session
        self.session = None
        if dropped and dropped["writes"]:
            self.last_result = {"status": "session-ended", "reason": reason,
                                "writes": dropped["writes"]}
        return dropped

    def disable(self, reason):
        self.disabled_reason = reason

    def _result(self, status, reason, **values):
        result = {"status": status, "reason": reason, "executorVersion": EXECUTOR_VERSION}
        result.update(values)
        self.last_result = deepcopy(result)
        return result

    def execute(self, action, observation, settings, now_ms):
        if self.disabled_reason:
            return self._result("blocked", "自动写入已停用：%s" % self.disabled_reason)
        kind = action.get("kind")
        if kind not in {"lower", "recover"} or not action.get("execute"):
            return self._result("blocked", "不是可执行的音量动作")
        if kind == "recover" and settings["mode"] != "automatic":
            return self._result("blocked", "只有自动调节模式允许回升")
        if observation.get("muted"):
            return self._result("blocked", "设备已静音，不调整音量")
        if self.session is None or self.session["deviceId"] != observation["deviceId"]:
            self.begin(observation)
        session = self.session
        before_db = observation.get("systemVolumeDb")
        before = observation.get("systemVolume")
        target_db = action.get("recommendedVolumeDb")
        if before_db is None or before is None or target_db is None:
            return self._result("blocked", "缺少当前或目标 dB")
        last_at = session["lastWriteAtMs"]
        if last_at is not None:
            since = now_ms - last_at
            if since < MIN_WRITE_INTERVAL_MS:
                return self._result("blocked", "写入间隔过短")
            if (since < STALE_READ_MS and session["lastWrittenVolumeDb"] is not None
                    and abs(before_db - session["lastWrittenVolumeDb"]) > 0.05):
                return self._result("blocked", "等待音量回读刷新，跳过基于旧读数的决策")
        elapsed_s = 1.0 if last_at is None else min(1.0, max(0.25, (now_ms - last_at) / 1000))
        if kind == "lower":
            return self._lower(session, observation, settings, now_ms, before, before_db,
                               float(target_db), elapsed_s)
        return self._raise(session, observation, settings, now_ms, before, before_db,
                           float(target_db), elapsed_s)

    def _write(self, method, session, now_ms, target, *arguments, **keywords):
        try:
            written = method(target, session["deviceId"], *arguments, **keywords)
        except (ValueError, RuntimeError) as error:
            # Device switched or volume moved under us: the user is in charge now.
            self.interrupt(str(error))
            return None, self._result("blocked", str(error))
        except Exception as error:  # COM / OS failure: stop writing entirely
            self.disable("写入失败：%s" % (str(error) or type(error).__name__))
            return None, self._result("failed", self.disabled_reason)
        return written, None

    def _record(self, session, written, now_ms, raised=False):
        session.update(lastWrittenVolume=written.get("appliedVolume"),
                       lastWrittenVolumeDb=written.get("appliedVolumeDb"),
                       lastWriteAtMs=now_ms, writes=session["writes"] + 1)
        if raised:
            session["raises"] += 1

    def _lower(self, session, observation, settings, now_ms, before, before_db, target_db,
               elapsed_s):
        rate_cap = settings["maxLowerDbPerSecond"] * elapsed_s
        step = min(before_db - target_db, rate_cap, MAX_WRITE_STEP_DB)
        if step <= 0.01:
            return self._result("blocked", "建议值不低于当前音量")
        floor_db = session["baselineVolumeDb"] - settings["maxAutoAttenuationDb"]
        target = max(before_db - step, floor_db)
        if target >= before_db - 0.01:
            return self._result("blocked", "已达到本次自动压低上限 %.1f dB"
                                % settings["maxAutoAttenuationDb"])
        if before <= settings["minSystemVolume"] + 0.05:
            return self._result("blocked", "已达到最低系统音量 %.0f%%" % settings["minSystemVolume"])
        written, blocked = self._write(self.source.apply_volume_db, session, now_ms, target,
                                       before_db, floor_percent=settings["minSystemVolume"])
        if blocked:
            return blocked
        applied_db = written.get("appliedVolumeDb")
        applied = written.get("appliedVolume")
        if (written.get("deviceId") != session["deviceId"] or applied is None
                or applied > written.get("beforeVolume", before) + 0.05
                or (not written.get("floored") and (
                    applied_db is None or abs(applied_db - target) > READBACK_TOLERANCE_DB))):
            self.disable("写入回读不一致（目标 %.2f dB，回读 %s dB）" % (target, applied_db))
            self._record(session, written, now_ms)
            return self._result("failed", self.disabled_reason, **written)
        self._record(session, written, now_ms)
        self.write_count += 1
        return self._result("applied", "已按 dB 压低系统音量", direction="lower",
                            targetVolumeDb=round(target, 3),
                            sessionAttenuationDb=round(
                                (applied_db if applied_db is not None else target)
                                - session["baselineVolumeDb"], 3),
                            **written)

    def _raise(self, session, observation, settings, now_ms, before, before_db, target_db,
               elapsed_s):
        ceiling_db = session["baselineVolumeDb"]
        ceiling = session["baselineVolume"]
        if before_db >= ceiling_db - 0.05 or before >= ceiling - 0.05:
            return self._result("blocked", "已回到本次基准音量，不再升高")
        rate_cap = settings["maxRaiseDbPerSecond"] * elapsed_s
        step = min(target_db - before_db, rate_cap, MAX_WRITE_STEP_DB)
        if step <= 0.01:
            return self._result("blocked", "建议值不高于当前音量")
        target = min(before_db + step, ceiling_db)
        written, blocked = self._write(self.source.raise_volume_db, session, now_ms, target,
                                       before_db, ceiling_percent=ceiling)
        if blocked:
            return blocked
        applied_db = written.get("appliedVolumeDb")
        applied = written.get("appliedVolume")
        if (written.get("deviceId") != session["deviceId"] or applied is None
                or applied < written.get("beforeVolume", before) - 0.05
                or applied > ceiling + CEILING_TOLERANCE_PERCENT
                or (not written.get("capped") and (
                    applied_db is None or abs(applied_db - target) > READBACK_TOLERANCE_DB))):
            self.disable("回升写入回读不一致（目标 %.2f dB，回读 %s dB / %s%%，基准 %.2f%%）" % (
                target, applied_db, applied, ceiling))
            self._record(session, written, now_ms, raised=True)
            return self._result("failed", self.disabled_reason, **written)
        self._record(session, written, now_ms, raised=True)
        self.write_count += 1
        self.raise_count += 1
        return self._result("applied", "已按 dB 回升系统音量", direction="raise",
                            targetVolumeDb=round(target, 3),
                            sessionAttenuationDb=round(
                                (applied_db if applied_db is not None else target)
                                - session["baselineVolumeDb"], 3),
                            **written)

    def restore(self, reason):
        session = self.session
        self.session = None
        if not session or not session["writes"]:
            return None
        if (session["lastWrittenVolume"] is not None
                and abs(session["lastWrittenVolume"] - session["baselineVolume"]) <= 0.05):
            return self._result("restored", "%s（已在基准音量，无需恢复）" % reason,
                                appliedVolume=session["lastWrittenVolume"],
                                appliedVolumeDb=session["lastWrittenVolumeDb"])
        try:
            restored = self.source.restore_volume(
                session["baselineVolume"], session["deviceId"], session["lastWrittenVolume"])
            return self._result("restored", reason, **restored)
        except Exception as error:
            return self._result("restore-refused", "%s：%s" % (reason, error))

    def status(self):
        return {
            "version": EXECUTOR_VERSION,
            "supported": self.supported(self.source),
            "supportsRaise": self.supports_raise(self.source),
            "disabledReason": self.disabled_reason,
            "writeCount": self.write_count,
            "raiseCount": self.raise_count,
            "session": deepcopy(self.session),
            "lastResult": deepcopy(self.last_result),
        }
