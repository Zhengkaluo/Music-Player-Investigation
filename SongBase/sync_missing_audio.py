#!/usr/bin/env python3
"""下载曲库中已有播放链接、但 SongResources 尚未保存的音频。

默认行为：
1. 比较 song_base_by_artist.json 与 SongResources 中的音频文件；
2. 优先使用 YouTube，失败后尝试 Bilibili；
3. 启动本地监控页面并在后台顺序下载；
4. 将实时状态写入 _audio_download_status.json。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


BASE = Path(__file__).resolve().parent
LIBRARY_PATH = BASE / "song_base_by_artist.json"
RESOURCES_DIR = BASE / "SongResources"
DASHBOARD_PATH = BASE / "audio_download_monitor.html"
STATUS_PATH = BASE / "_audio_download_status.json"
LOG_PATH = RESOURCES_DIR / "_audio_download_log.txt"

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wav"}
FALLBACK_YTDLP = Path(
    "/Users/kaluozheng/.workbuddy/skills/video-audio-to-mp3/venv/bin/yt-dlp"
)
FALLBACK_FFMPEG = Path(
    "/Users/kaluozheng/.workbuddy/skills/video-audio-to-mp3/venv/lib/"
    "python3.13/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
)
FALLBACK_NODE = Path(
    "/Users/kaluozheng/.workbuddy/binaries/node/versions/22.22.2/bin/node"
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def clean_filename(value: str) -> str:
    value = unicodedata.normalize("NFC", str(value or ""))
    value = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value or "未命名"


def truncate_utf8(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    encoded = encoded[:max_bytes]
    while encoded:
        try:
            return encoded.decode("utf-8").rstrip()
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    return "未命名"


def normalized_stem(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return "".join(char for char in value if char.isalnum())


def artist_variants(group_artist: str, full_singer: str) -> list[str]:
    values: list[str] = []
    for artist in (group_artist, full_singer):
        artist = str(artist or "").strip()
        if not artist:
            continue
        values.append(artist)
        for separator in (",", "，", "&", "、"):
            primary = artist.split(separator, 1)[0].strip()
            if primary:
                values.append(primary)
    return list(dict.fromkeys(values))


def target_filename(title: str, artist: str) -> str:
    stem = f"{clean_filename(title)} - {clean_filename(artist)}"
    return f"{truncate_utf8(stem, 235)}.mp3"


def find_executable(explicit: str, command: str, fallback: Path | None = None) -> str:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"找不到 {command}: {path}")
        return str(path)
    found = shutil.which(command)
    if found:
        return found
    if fallback and fallback.is_file():
        return str(fallback)
    return ""


def build_audio_index(resources_dir: Path) -> tuple[set[str], set[str], int]:
    exact: set[str] = set()
    compact: set[str] = set()
    count = 0
    if not resources_dir.exists():
        return exact, compact, count
    for path in resources_dir.iterdir():
        if not path.is_file() or path.suffix.casefold() not in AUDIO_EXTENSIONS:
            continue
        if path.stat().st_size <= 0:
            continue
        count += 1
        exact.add(unicodedata.normalize("NFC", path.stem).casefold())
        compact.add(normalized_stem(path.stem))
    return exact, compact, count


def local_song_exists(
    title: str,
    group_artist: str,
    full_singer: str,
    exact_stems: set[str],
    compact_stems: set[str],
) -> bool:
    for artist in artist_variants(group_artist, full_singer):
        stem = Path(target_filename(title, artist)).stem
        if unicodedata.normalize("NFC", stem).casefold() in exact_stems:
            return True
        if normalized_stem(stem) in compact_stems:
            return True
    return False


def scan_library(
    library_path: Path = LIBRARY_PATH,
    resources_dir: Path = RESOURCES_DIR,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    library = json.loads(library_path.read_text(encoding="utf-8"))
    singers = library.get("singers")
    if not isinstance(singers, list):
        raise ValueError("曲库缺少 singers 数组")

    exact_stems, compact_stems, local_count = build_audio_index(resources_dir)
    tasks: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    total_songs = 0
    linked_songs = 0
    duplicate_tasks = 0

    for singer in singers:
        group_artist = str(singer.get("name", "")).strip()
        for song in singer.get("songs", []):
            total_songs += 1
            youtube = str(song.get("youtube", "") or "").strip()
            bilibili = str(song.get("bilibili", "") or "").strip()
            if not youtube and not bilibili:
                continue
            linked_songs += 1

            title = str(song.get("title", "")).strip()
            full_singer = str(song.get("full_singer", "") or "").strip()
            if local_song_exists(
                title,
                group_artist,
                full_singer,
                exact_stems,
                compact_stems,
            ):
                continue

            filename = target_filename(title, group_artist or full_singer)
            target_key = normalized_stem(Path(filename).stem)
            if target_key in seen_targets:
                duplicate_tasks += 1
                continue
            seen_targets.add(target_key)

            sources = []
            if youtube:
                sources.append({"provider": "YouTube", "url": youtube})
            if bilibili:
                sources.append({"provider": "Bilibili", "url": bilibili})

            tasks.append(
                {
                    "id": len(tasks) + 1,
                    "title": title,
                    "artist": group_artist or full_singer or "未知艺人",
                    "full_singer": full_singer,
                    "album": str(song.get("album", "") or "未标注专辑"),
                    "duration": int(song.get("duration", 0) or 0),
                    "filename": filename,
                    "sources": sources,
                    "provider": sources[0]["provider"],
                    "status": "pending",
                    "message": "等待下载",
                    "size_mb": 0,
                    "started_at": "",
                    "finished_at": "",
                }
            )

    summary = {
        "library_songs": total_songs,
        "linked_songs": linked_songs,
        "local_audio": local_count,
        "missing": len(tasks),
        "deduplicated": duplicate_tasks,
    }
    return tasks, summary


class DownloadState:
    def __init__(self, tasks: list[dict[str, Any]], scan: dict[str, int]) -> None:
        self.lock = threading.RLock()
        self.tasks = tasks
        self.scan = scan
        self.phase = "ready"
        self.started_at = ""
        self.updated_at = now_iso()
        self.finished_at = ""
        self.current_id: int | None = None
        self.stop_requested = False
        self.bytes_downloaded = 0
        self.logs: list[dict[str, str]] = []
        self.error = ""

    def log(self, message: str, level: str = "info") -> None:
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,
            "message": message,
        }
        with self.lock:
            self.logs.append(entry)
            self.logs = self.logs[-200:]
            self.updated_at = now_iso()
        print(f"[{entry['time']}] {message}", flush=True)
        RESOURCES_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(f"[{entry['time']}] [{level}] {message}\n")

    def update_task(self, task_id: int, **changes: Any) -> None:
        with self.lock:
            task = self.tasks[task_id - 1]
            task.update(changes)
            self.updated_at = now_iso()
        self.persist()

    def persist(self) -> None:
        snapshot = self.snapshot()
        temporary = STATUS_PATH.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(STATUS_PATH)

    def request_stop(self) -> None:
        with self.lock:
            if self.phase not in {"ready", "downloading", "stopping"}:
                return
            self.stop_requested = True
            if self.phase in {"ready", "downloading"}:
                self.phase = "stopping"
            self.updated_at = now_iso()
        self.log("已请求停止；当前曲目处理完后停止。", "warning")

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            counts = {
                name: sum(1 for task in self.tasks if task["status"] == name)
                for name in ("pending", "downloading", "success", "failed", "skipped")
            }
            processed = counts["success"] + counts["failed"] + counts["skipped"]
            total = len(self.tasks)
            elapsed = 0
            if self.started_at:
                start = datetime.fromisoformat(self.started_at)
                end = (
                    datetime.fromisoformat(self.finished_at)
                    if self.finished_at
                    else datetime.now().astimezone()
                )
                elapsed = max(0, int((end - start).total_seconds()))
            eta = 0
            if processed and processed < total and elapsed:
                eta = int(elapsed / processed * (total - processed))
            disk_root = RESOURCES_DIR if RESOURCES_DIR.exists() else BASE
            disk_free_gb = round(shutil.disk_usage(disk_root).free / 1024**3, 1)
            return {
                "phase": self.phase,
                "scan": dict(self.scan),
                "counts": counts,
                "total": total,
                "processed": processed,
                "remaining": max(0, total - processed),
                "progress": round(processed / max(total, 1) * 100, 1),
                "started_at": self.started_at,
                "updated_at": self.updated_at,
                "finished_at": self.finished_at,
                "elapsed_seconds": elapsed,
                "eta_seconds": eta,
                "downloaded_mb": round(self.bytes_downloaded / 1024 / 1024, 1),
                "disk_free_gb": disk_free_gb,
                "current_id": self.current_id,
                "stop_requested": self.stop_requested,
                "error": self.error,
                "tasks": [dict(task) for task in self.tasks],
                "logs": list(self.logs),
            }


def command_for_source(
    source_url: str,
    output_template: Path,
    yt_dlp: str,
    ffmpeg: str,
    node: str,
    browser: str,
    use_cookies: bool,
) -> list[str]:
    command = [
        yt_dlp,
        "--no-playlist",
        "--no-warnings",
        "-f",
        "bestaudio",
        "--extract-audio",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "192K",
        "-o",
        str(output_template),
    ]
    if ffmpeg:
        command.extend(["--ffmpeg-location", ffmpeg])
    if node:
        command.extend(["--js-runtimes", f"node:{node}"])
    if browser and use_cookies:
        command.extend(["--cookies-from-browser", browser])
    command.append(source_url)
    return command


def concise_error(result: subprocess.CompletedProcess[str]) -> str:
    text = f"{result.stderr or ''}\n{result.stdout or ''}".strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return f"下载器退出码 {result.returncode}"
    return truncate_utf8(lines[-1], 420)


def run_source_download(
    source: dict[str, str],
    temporary_dir: Path,
    tools: dict[str, str],
    args: argparse.Namespace,
) -> tuple[Path | None, str]:
    output_template = temporary_dir / "%(title)s.%(ext)s"
    cookie_attempts = [not args.no_cookies]
    if not args.no_cookies:
        cookie_attempts.append(False)

    last_error = ""
    for use_cookies in cookie_attempts:
        command = command_for_source(
            source["url"],
            output_template,
            tools["yt_dlp"],
            tools["ffmpeg"],
            tools["node"],
            args.browser,
            use_cookies,
        )
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=args.timeout,
            )
        except subprocess.TimeoutExpired:
            last_error = f"{source['provider']} 下载超时（{args.timeout} 秒）"
            continue

        if result.returncode == 0:
            outputs = sorted(
                temporary_dir.rglob("*.mp3"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if outputs:
                return outputs[0], ""
            last_error = f"{source['provider']} 未生成 MP3"
            continue

        last_error = concise_error(result)
        cookie_problem = any(
            word in last_error.casefold()
            for word in ("cookie", "firefox", "profile", "keyring")
        )
        if use_cookies and cookie_problem:
            continue
        break
    return None, last_error


def download_task(
    task: dict[str, Any],
    state: DownloadState,
    tools: dict[str, str],
    args: argparse.Namespace,
) -> tuple[bool, str]:
    target = RESOURCES_DIR / task["filename"]
    if target.exists() and target.stat().st_size > 0:
        return True, "文件已由其他任务写入"

    errors = []
    for source in task["sources"]:
        state.update_task(
            task["id"],
            provider=source["provider"],
            message=f"正在从 {source['provider']} 下载",
        )
        with tempfile.TemporaryDirectory(prefix="songbase-audio-") as temp_name:
            output, error = run_source_download(
                source,
                Path(temp_name),
                tools,
                args,
            )
            if output:
                RESOURCES_DIR.mkdir(parents=True, exist_ok=True)
                shutil.move(str(output), str(target))
                size = target.stat().st_size
                if size <= 0:
                    errors.append(f"{source['provider']} 生成了空文件")
                    continue
                with state.lock:
                    state.bytes_downloaded += size
                return True, f"{source['provider']} · {size / 1024 / 1024:.1f} MB"
            errors.append(f"{source['provider']}: {error}")
    return False, "；".join(errors)


def download_worker(
    state: DownloadState,
    tools: dict[str, str],
    args: argparse.Namespace,
    server: ThreadingHTTPServer,
) -> None:
    with state.lock:
        state.phase = "downloading"
        state.started_at = now_iso()
        state.updated_at = state.started_at
    state.log(f"发现 {len(state.tasks)} 首需要下载。")
    state.persist()

    try:
        for task in state.tasks:
            with state.lock:
                if state.stop_requested:
                    break
                state.current_id = task["id"]
            state.update_task(
                task["id"],
                status="downloading",
                started_at=now_iso(),
                message=f"准备从 {task['provider']} 下载",
            )
            state.log(
                f"[{task['id']}/{len(state.tasks)}] "
                f"{task['title']} — {task['artist']}"
            )

            if args.dry_run:
                ok, message = True, "模拟运行：未写入音频"
                status = "skipped"
            else:
                ok, message = download_task(task, state, tools, args)
                status = "success" if ok else "failed"

            size_mb = 0
            target = RESOURCES_DIR / task["filename"]
            if target.exists() and target.stat().st_size > 0:
                size_mb = round(target.stat().st_size / 1024 / 1024, 1)
            state.update_task(
                task["id"],
                status=status,
                message=message,
                size_mb=size_mb,
                finished_at=now_iso(),
            )
            state.log(
                f"{'完成' if ok else '失败'}：{task['title']} · {message}",
                "success" if ok else "error",
            )
            if not args.dry_run and args.delay > 0:
                time.sleep(args.delay)

        with state.lock:
            state.current_id = None
            state.finished_at = now_iso()
            state.phase = "stopped" if state.stop_requested else "completed"
            state.updated_at = state.finished_at
        state.log("下载任务已停止。" if state.stop_requested else "全部任务处理完成。")
    except Exception as exc:
        with state.lock:
            state.phase = "error"
            state.error = str(exc)
            state.finished_at = now_iso()
            state.current_id = None
        state.log(f"任务异常终止：{exc}", "error")
    finally:
        state.persist()
        if args.exit_when_done:
            threading.Timer(0.2, server.shutdown).start()


def make_handler(state: DownloadState) -> type[BaseHTTPRequestHandler]:
    class MonitorHandler(BaseHTTPRequestHandler):
        def send_body(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/api/status":
                body = json.dumps(state.snapshot(), ensure_ascii=False).encode("utf-8")
                self.send_body(200, "application/json; charset=utf-8", body)
                return
            if path in {"/", "/index.html"}:
                try:
                    body = DASHBOARD_PATH.read_bytes()
                except OSError as exc:
                    self.send_body(
                        500,
                        "text/plain; charset=utf-8",
                        f"无法读取监控页面：{exc}".encode("utf-8"),
                    )
                    return
                self.send_body(200, "text/html; charset=utf-8", body)
                return
            self.send_body(404, "text/plain; charset=utf-8", b"Not found")

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if path == "/api/stop":
                state.request_stop()
                body = json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8")
                self.send_body(200, "application/json; charset=utf-8", body)
                return
            self.send_body(404, "application/json; charset=utf-8", b'{"ok":false}')

        def log_message(self, *_args: Any) -> None:
            pass

    return MonitorHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="比较 SongBase 曲库与本地音频，并下载缺失曲目。"
    )
    parser.add_argument("--port", type=int, default=8766, help="监控页面端口")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--scan-only", action="store_true", help="只扫描并输出统计")
    parser.add_argument("--dry-run", action="store_true", help="显示任务但不下载")
    parser.add_argument(
        "--exit-when-done",
        action="store_true",
        help="完成后关闭监控服务并退出",
    )
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 首")
    parser.add_argument("--delay", type=float, default=1.5, help="任务间隔秒数")
    parser.add_argument("--timeout", type=int, default=600, help="单个来源超时秒数")
    parser.add_argument("--browser", default="firefox", help="读取 Cookie 的浏览器")
    parser.add_argument("--no-cookies", action="store_true", help="不读取浏览器 Cookie")
    parser.add_argument("--yt-dlp", default="", help="yt-dlp 可执行文件路径")
    parser.add_argument("--ffmpeg", default="", help="FFmpeg 可执行文件路径")
    parser.add_argument("--node", default="", help="Node.js 可执行文件路径")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not LIBRARY_PATH.exists():
        print(f"曲库不存在：{LIBRARY_PATH}", file=sys.stderr)
        return 1
    if not DASHBOARD_PATH.exists() and not args.scan_only:
        print(f"监控页面不存在：{DASHBOARD_PATH}", file=sys.stderr)
        return 1

    try:
        tasks, summary = scan_library()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"扫描曲库失败：{exc}", file=sys.stderr)
        return 1

    if args.limit > 0:
        tasks = tasks[: args.limit]
        for index, task in enumerate(tasks, 1):
            task["id"] = index
        summary["missing"] = len(tasks)

    if args.scan_only:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if tasks:
            print("\n前 10 个任务：")
            for task in tasks[:10]:
                print(
                    f"- {task['title']} — {task['artist']} "
                    f"({task['provider']})"
                )
        return 0

    try:
        yt_dlp = find_executable(args.yt_dlp, "yt-dlp", FALLBACK_YTDLP)
        if not yt_dlp and not args.dry_run:
            raise FileNotFoundError("找不到 yt-dlp")
        tools = {
            "yt_dlp": yt_dlp,
            "ffmpeg": find_executable(args.ffmpeg, "ffmpeg", FALLBACK_FFMPEG),
            "node": find_executable(args.node, "node", FALLBACK_NODE),
        }
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    state = DownloadState(tasks, summary)
    try:
        server = ThreadingHTTPServer(
            ("127.0.0.1", args.port),
            make_handler(state),
        )
    except OSError as exc:
        if args.port == 0:
            print(f"无法启动监控服务：{exc}", file=sys.stderr)
            return 1
        print(f"端口 {args.port} 不可用，改用系统分配的空闲端口。")
        try:
            server = ThreadingHTTPServer(
                ("127.0.0.1", 0),
                make_handler(state),
            )
        except OSError as fallback_exc:
            print(f"无法启动监控服务：{fallback_exc}", file=sys.stderr)
            return 1
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"下载监控：{url}")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    if tasks:
        worker = threading.Thread(
            target=download_worker,
            args=(state, tools, args, server),
            daemon=True,
        )
        worker.start()
    else:
        state.phase = "completed"
        state.started_at = state.finished_at = now_iso()
        state.log("本地音频已完整，无需下载。")
        state.persist()
        if args.exit_when_done:
            threading.Timer(0.2, server.shutdown).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        state.request_stop()
        print("\n监控服务已关闭。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
