"""
轻量终端状态行输出工具。
"""
from __future__ import annotations

import sys
import threading


_lock = threading.Lock()
_last_line_length = 0


def render_status(message: str) -> None:
    """在交互式终端中用单行刷新展示状态。"""
    global _last_line_length

    if not sys.stderr.isatty():
        return

    line = f"[status] {message}"
    with _lock:
        padded = line.ljust(_last_line_length)
        sys.stderr.write(f"\r{padded}")
        sys.stderr.flush()
        _last_line_length = max(_last_line_length, len(line))


def clear_status() -> None:
    """清除最后一条状态行。"""
    global _last_line_length

    if not sys.stderr.isatty() or _last_line_length == 0:
        return

    with _lock:
        sys.stderr.write("\r" + (" " * _last_line_length) + "\r")
        sys.stderr.flush()
        _last_line_length = 0
