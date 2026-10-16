"""Small streaming ITU-R BS.1770 K-weighted loudness meter."""

from __future__ import annotations

from collections import deque
import math


def k_weighting_coefficients(sample_rate):
    """Return shelf and RLB biquads; values match BS.1770 at 48 kHz."""
    sample_rate = float(sample_rate)
    if not 8000 <= sample_rate <= 384000:
        raise ValueError("sample_rate 必须在 8000..384000 Hz")

    frequency = 1681.974450955533
    gain = 3.999843853973347
    quality = 0.7071752369554196
    k = math.tan(math.pi * frequency / sample_rate)
    vh = 10 ** (gain / 20)
    vb = vh ** 0.4996667741545416
    denominator = 1 + k / quality + k * k
    shelf = (
        (vh + vb * k / quality + k * k) / denominator,
        2 * (k * k - vh) / denominator,
        (vh - vb * k / quality + k * k) / denominator,
        2 * (k * k - 1) / denominator,
        (1 - k / quality + k * k) / denominator,
    )

    frequency = 38.13547087602444
    quality = 0.5003270373238773
    k = math.tan(math.pi * frequency / sample_rate)
    denominator = 1 + k / quality + k * k
    high_pass = (
        1.0,
        -2.0,
        1.0,
        2 * (k * k - 1) / denominator,
        (1 - k / quality + k * k) / denominator,
    )
    return shelf, high_pass


class Biquad:
    __slots__ = ("b0", "b1", "b2", "a1", "a2", "z1", "z2")

    def __init__(self, coefficients):
        self.b0, self.b1, self.b2, self.a1, self.a2 = coefficients
        self.z1 = self.z2 = 0.0

    def process(self, value):
        result = self.b0 * value + self.z1
        self.z1 = self.b1 * value - self.a1 * result + self.z2
        self.z2 = self.b2 * value - self.a2 * result
        return result


class LoudnessMeter:
    """Consume normalized interleaved PCM and expose 400 ms / 3 s LUFS."""

    CHANNEL_WEIGHTS = {
        1: (1.0,),
        2: (1.0, 1.0),
        3: (1.0, 1.0, 1.0),
        4: (1.0, 1.0, 1.41, 1.41),
        5: (1.0, 1.0, 1.0, 1.41, 1.41),
        6: (1.0, 1.0, 1.0, 0.0, 1.41, 1.41),
        7: (1.0, 1.0, 1.0, 0.0, 1.0, 1.41, 1.41),
        8: (1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.41, 1.41),
    }

    def __init__(self, sample_rate, channels):
        if channels not in self.CHANNEL_WEIGHTS:
            raise ValueError("channels 必须在 1..8")
        self.sample_rate = float(sample_rate)
        self.channels = int(channels)
        self.weights = self.CHANNEL_WEIGHTS[self.channels]
        coefficients = k_weighting_coefficients(sample_rate)
        self.filters = [[Biquad(item) for item in coefficients]
                        for _ in range(self.channels)]
        self.block_frames = int(round(self.sample_rate / 10))
        self.block_energy = 0.0
        self.block_count = 0
        self.blocks = deque(maxlen=30)

    def consume(self, samples, scale=1.0):
        if len(samples) % self.channels:
            raise ValueError("PCM 样本数量必须是声道数的整数倍")
        for offset in range(0, len(samples), self.channels):
            energy = 0.0
            for channel in range(self.channels):
                value = float(samples[offset + channel]) * scale
                if not math.isfinite(value):
                    value = 0.0
                for biquad in self.filters[channel]:
                    value = biquad.process(value)
                energy += self.weights[channel] * value * value
            self.block_energy += energy
            self.block_count += 1
            if self.block_count == self.block_frames:
                self.blocks.append(self.block_energy / self.block_frames)
                self.block_energy = 0.0
                self.block_count = 0

    @staticmethod
    def _lufs(blocks):
        energy = sum(blocks) / len(blocks)
        return max(-120.0, -0.691 + 10 * math.log10(energy)) if energy > 0 else -120.0

    def reset(self):
        """Forget all windows and filter state, e.g. after the source went idle."""
        for channel_filters in self.filters:
            for biquad in channel_filters:
                biquad.z1 = biquad.z2 = 0.0
        self.block_energy = 0.0
        self.block_count = 0
        self.blocks.clear()

    def snapshot(self):
        blocks = list(self.blocks)
        return {
            "momentaryLufs": self._lufs(blocks[-4:]) if len(blocks) >= 4 else None,
            "shortTermLufs": self._lufs(blocks[-30:]) if len(blocks) >= 30 else None,
            "loudnessBlocks": len(blocks),
        }


class PeakGuard:
    """10 ms burst detector. It only reports suggested attenuation."""

    def __init__(self, sample_rate, channels, peak_threshold_dbfs=-1.0,
                 relative_jump_db=10.0, min_duration_ms=20, hold_ms=500,
                 release_ms=2000, cooldown_ms=1000, max_attenuation_db=12.0):
        if not 8000 <= float(sample_rate) <= 384000:
            raise ValueError("sample_rate 必须在 8000..384000 Hz")
        if not 1 <= int(channels) <= 8:
            raise ValueError("channels 必须在 1..8")
        self.channels = int(channels)
        self.block_frames = int(round(float(sample_rate) / 100))
        self.warmup_blocks = 100
        self.min_blocks = max(1, math.ceil(min_duration_ms / 10))
        self.hold_blocks = max(1, math.ceil(hold_ms / 10))
        self.release_blocks = max(1, math.ceil(release_ms / 10))
        self.cooldown_blocks = max(0, math.ceil(cooldown_ms / 10))
        self.peak_threshold_dbfs = float(peak_threshold_dbfs)
        self.relative_jump_db = float(relative_jump_db)
        self.max_attenuation_db = float(max_attenuation_db)
        self.baseline_alpha = 1 - math.exp(-0.01)
        self.baseline_energy = 10 ** (-60 / 10)
        self.block_energy = self.block_peak = 0.0
        self.frame_count = self.candidate_blocks = 0
        self.hold_remaining = self.release_remaining = self.cooldown_remaining = 0
        self.state = "ARMED"
        self.attenuation_db = 0.0
        self.attack_attenuation_db = 0.0
        self.trigger_count = 0
        self.block_index = 0
        self.fast_rms_dbfs = self.baseline_rms_dbfs = self.relative_jump = None
        self.sample_peak_dbfs = None
        self.last_trigger = None

    @staticmethod
    def _db(value):
        return max(-120.0, 10 * math.log10(value)) if value > 0 else -120.0

    def consume(self, samples, scale=1.0):
        if len(samples) % self.channels:
            raise ValueError("PCM 样本数量必须是声道数的整数倍")
        for offset in range(0, len(samples), self.channels):
            energy = peak = 0.0
            for channel in range(self.channels):
                value = float(samples[offset + channel]) * scale
                if not math.isfinite(value):
                    value = 0.0
                energy += value * value
                peak = max(peak, abs(value))
            self.block_energy += energy / self.channels
            self.block_peak = max(self.block_peak, peak)
            self.frame_count += 1
            if self.frame_count == self.block_frames:
                self._finish_block()

    def _finish_block(self):
        energy = self.block_energy / self.block_frames
        self.fast_rms_dbfs = self._db(energy)
        self.baseline_rms_dbfs = self._db(self.baseline_energy)
        self.sample_peak_dbfs = self._db(self.block_peak * self.block_peak)
        self.relative_jump = max(0.0, self.fast_rms_dbfs - self.baseline_rms_dbfs)
        self.block_index += 1
        condition = (self.block_index >= self.warmup_blocks
                     and self.sample_peak_dbfs >= self.peak_threshold_dbfs
                     and self.relative_jump >= self.relative_jump_db)

        if self.state == "ARMED":
            if self.cooldown_remaining:
                self.cooldown_remaining -= 1
                self.candidate_blocks = 0
            elif condition:
                self.candidate_blocks += 1
                if self.candidate_blocks >= self.min_blocks:
                    self.attack_attenuation_db = -min(
                        self.max_attenuation_db, self.relative_jump)
                    self.attenuation_db = self.attack_attenuation_db
                    self.state = "ATTACK"
                    self.trigger_count += 1
                    self.last_trigger = {
                        "blockIndex": self.block_index,
                        "samplePeakDbfs": self.sample_peak_dbfs,
                        "fastRmsDbfs": self.fast_rms_dbfs,
                        "baselineRmsDbfs": self.baseline_rms_dbfs,
                        "relativeJumpDb": self.relative_jump,
                        "suggestedAttenuationDb": self.attenuation_db,
                    }
                    self.candidate_blocks = 0
            else:
                self.candidate_blocks = 0
                self.baseline_energy += self.baseline_alpha * (energy - self.baseline_energy)
        elif self.state == "ATTACK":
            self.state = "HOLD"
            self.hold_remaining = self.hold_blocks
        elif self.state == "HOLD":
            self.hold_remaining -= 1
            if self.hold_remaining <= 0:
                self.state = "RELEASE"
                self.release_remaining = self.release_blocks
        elif self.state == "RELEASE":
            self.release_remaining -= 1
            self.attenuation_db = self.attack_attenuation_db * (
                max(0, self.release_remaining) / self.release_blocks)
            if self.release_remaining <= 0:
                self.state = "ARMED"
                self.attenuation_db = 0.0
                self.cooldown_remaining = self.cooldown_blocks

        self.block_energy = self.block_peak = 0.0
        self.frame_count = 0

    def snapshot(self):
        return {
            "mode": "shadow",
            "state": self.state,
            "warmedUp": self.block_index >= self.warmup_blocks,
            "samplePeakDbfs": self.sample_peak_dbfs,
            "truePeakDbtp": None,
            "fastRmsDbfs": self.fast_rms_dbfs,
            "baselineRmsDbfs": self.baseline_rms_dbfs,
            "relativeJumpDb": self.relative_jump,
            "suggestedAttenuationDb": self.attenuation_db,
            "triggerCount": self.trigger_count,
            "lastTrigger": self.last_trigger,
            "execute": False,
        }
