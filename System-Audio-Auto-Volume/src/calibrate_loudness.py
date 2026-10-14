"""Compare the realtime meter with FFmpeg ebur128 using generated test tones."""

from __future__ import annotations

import argparse
from array import array
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import wave

from loudness_meter import LoudnessMeter


def pcm_tone(sample_rate, seconds, frequency, amplitude, channels=2):
    values = array("h")
    for frame in range(round(sample_rate * seconds)):
        sample = round(math.sin(2 * math.pi * frequency * frame / sample_rate)
                       * amplitude * 32767)
        values.extend([sample] * channels)
    return values


def ffmpeg_loudness(ffmpeg, path):
    result = subprocess.run(
        [str(ffmpeg), "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
         "ebur128=metadata=1,ametadata=print:key=lavfi.r128.M,"
         "ametadata=print:key=lavfi.r128.S", "-f", "null", "-"],
        capture_output=True, text=True, check=True, timeout=60,
    )
    values = {}
    for key in ("M", "S"):
        matches = re.findall(r"lavfi\.r128\.%s=([-\d.]+)" % key, result.stderr)
        if not matches:
            raise RuntimeError("FFmpeg 没有返回 %s 响度" % key)
        values[key] = float(matches[-1])
    return values


def run_case(ffmpeg, sample_rate, frequency, amplitude=0.125, seconds=4):
    pcm = pcm_tone(sample_rate, seconds, frequency, amplitude)
    meter = LoudnessMeter(sample_rate, 2)
    started = time.perf_counter()
    meter.consume(pcm, scale=1 / 32768)
    elapsed = time.perf_counter() - started
    realtime = meter.snapshot()
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "tone.wav"
        with wave.open(str(path), "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(pcm.tobytes())
        reference = ffmpeg_loudness(ffmpeg, path)
    return {
        "sampleRate": sample_rate,
        "frequencyHz": frequency,
        "momentaryLufs": round(realtime["momentaryLufs"], 3),
        "shortTermLufs": round(realtime["shortTermLufs"], 3),
        "ffmpegMomentaryLufs": reference["M"],
        "ffmpegShortTermLufs": reference["S"],
        "momentaryErrorLu": round(realtime["momentaryLufs"] - reference["M"], 3),
        "shortTermErrorLu": round(realtime["shortTermLufs"] - reference["S"], 3),
        "processingSeconds": round(elapsed, 4),
        "realtimeFactor": round(seconds / elapsed, 2),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", type=Path,
                        default=Path(shutil.which("ffmpeg")) if shutil.which("ffmpeg") else None)
    args = parser.parse_args()
    if args.ffmpeg is None or not args.ffmpeg.is_file():
        parser.error("请用 --ffmpeg 指定可执行文件")
    cases = [run_case(args.ffmpeg, rate, frequency)
             for rate in (44100, 48000) for frequency in (100, 1000, 10000)]
    print(json.dumps({"schemaVersion": "system-audio.loudness-calibration/v1",
                      "cases": cases}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
