#!/usr/bin/env python3
"""Serve SongBase HTML and audio locally with byte-range support."""

from __future__ import annotations

import argparse
import os
import re
import shutil
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class RangeHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        try:
            source = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return None

        size = os.fstat(source.fileno()).st_size
        start, end = 0, size - 1
        requested = self.headers.get("Range")
        if requested:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested.strip())
            if not match:
                source.close()
                self.send_error(416, "Invalid range")
                return None
            left, right = match.groups()
            if left:
                start = int(left)
                end = min(int(right), end) if right else end
            elif right:
                start = max(0, size - int(right))
            if start > end or start >= size:
                source.close()
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return None
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self._range = (start, end)
        else:
            self.send_response(200)
            self._range = None

        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header(
            "Last-Modified",
            self.date_time_string(os.fstat(source.fileno()).st_mtime),
        )
        self.end_headers()
        source.seek(start)
        return source

    def copyfile(self, source, output):
        if self._range is None:
            return shutil.copyfileobj(source, output)
        remaining = self._range[1] - self._range[0] + 1
        while remaining:
            chunk = source.read(min(256 * 1024, remaining))
            if not chunk:
                break
            output.write(chunk)
            remaining -= len(chunk)

    def log_message(self, *_args):
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args()
    os.chdir(Path(__file__).resolve().parent)
    print(f"SongBase: http://127.0.0.1:{args.port}/song_tags_browser.html")
    ThreadingHTTPServer(("127.0.0.1", args.port), RangeHandler).serve_forever()


if __name__ == "__main__":
    main()
