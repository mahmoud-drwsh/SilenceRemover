"""Filesystem helpers shared across modules."""

from __future__ import annotations

import os
import time
from pathlib import Path

try:
    import ctypes
    from ctypes import wintypes
except ImportError:  # pragma: no cover - non-Windows environments
    ctypes = None
    wintypes = None

__all__ = ["wait_for_file_release"]

_IS_WINDOWS = os.name == "nt"
_WAIT_TIMEOUT_SEC = float(os.environ.get("SILENCE_REMOVER_WAIT_TIMEOUT_SEC", "30"))
_WAIT_SLEEP_SEC = float(os.environ.get("SILENCE_REMOVER_WAIT_SLEEP_SEC", "0.25"))

if _IS_WINDOWS and ctypes:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CreateFileW = _kernel32.CreateFileW
    _CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _CreateFileW.restype = wintypes.HANDLE
    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]
    _CloseHandle.restype = wintypes.BOOL

    _INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value  # type: ignore[arg-type]
    _OPEN_EXISTING = 3
    _DELETE = 0x00010000
    _FILE_READ_ATTRIBUTES = 0x80
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _FILE_SHARE_DELETE = 0x00000004
    _ERROR_FILE_NOT_FOUND = 2
    _ERROR_PATH_NOT_FOUND = 3
else:  # pragma: no cover - non-Windows environments
    _CreateFileW = None
    _CloseHandle = None
    _INVALID_HANDLE_VALUE = None
    _OPEN_EXISTING = None
    _DELETE = None
    _FILE_READ_ATTRIBUTES = None
    _FILE_SHARE_READ = None
    _FILE_SHARE_WRITE = None
    _FILE_SHARE_DELETE = None
    _ERROR_FILE_NOT_FOUND = None
    _ERROR_PATH_NOT_FOUND = None


def wait_for_file_release(path: Path, timeout: float = _WAIT_TIMEOUT_SEC) -> bool:
    """On Windows wait until path can be opened for delete access."""
    if not (_IS_WINDOWS and _CreateFileW):
        return True
    deadline = time.monotonic() + timeout
    waited = False
    while True:
        handle = _CreateFileW(
            str(path),
            _DELETE | _FILE_READ_ATTRIBUTES,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
            None,
            _OPEN_EXISTING,
            0,
            None,
        )
        if handle != _INVALID_HANDLE_VALUE:
            _CloseHandle(handle)
            if waited:
                print(f"Lock released: '{path.name}' is now writable.")
            return True
        err = ctypes.get_last_error()
        if err in (_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND):
            return False
        if not waited:
            print(f"Waiting for '{path.name}' to become unlockable...")
            waited = True
        if time.monotonic() >= deadline:
            print(
                f"Timed out waiting for '{path.name}' to be freed "
                f"({timeout:.1f}s). Another process may still hold it."
            )
            return False
        time.sleep(_WAIT_SLEEP_SEC)

