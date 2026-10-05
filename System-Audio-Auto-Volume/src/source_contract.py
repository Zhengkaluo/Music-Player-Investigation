"""Shared contract implemented by simulator and platform audio sources."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable


@runtime_checkable
class AudioSource(Protocol):
    platform: str
    simulated: bool
    measurement_source: str

    def observe(self, timestamp_ms: float) -> Mapping[str, Any]: ...

    def close(self) -> None: ...


def validate_source(source: object) -> AudioSource:
    if not isinstance(source, AudioSource):
        raise TypeError("音频源必须实现 AudioSource 接口")
    if source.platform not in {"simulator", "macos", "windows"}:
        raise ValueError("不支持的音频源平台：%s" % source.platform)
    if not source.measurement_source:
        raise ValueError("音频源必须声明 measurement_source")
    return source
