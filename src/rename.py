"""Video renaming functionality.

Windows can raise WinError 5 when a different process holds an open handle
without FILE_SHARE_DELETE (for example Explorer previews, antivirus scanners,
or indexing services). That prevents renames/deletes until the other handle
closes or the file is made writable again. When troubleshooting persistent
locks, inspecting handles with Process Explorer or Resource Monitor can reveal
the blocker."""

import os
import shutil
import stat
import time
from pathlib import Path
from typing import Optional

try:
    import ctypes
    from ctypes import wintypes
except ImportError:  # pragma: no cover - non-Windows environments
    ctypes = None
    wintypes = None


_IS_WINDOWS = os.name == "nt"
_RENAME_ATTEMPTS = int(os.environ.get("SILENCE_REMOVER_RENAME_ATTEMPTS", "8"))
_RENAME_SLEEP_SEC = float(os.environ.get("SILENCE_REMOVER_RENAME_SLEEP_SEC", "0.75"))
_DELETE_ATTEMPTS = int(os.environ.get("SILENCE_REMOVER_DELETE_ATTEMPTS", "5"))
_DELETE_SLEEP_SEC = float(os.environ.get("SILENCE_REMOVER_DELETE_SLEEP_SEC", "0.75"))
_WAIT_TIMEOUT_SEC = float(os.environ.get("SILENCE_REMOVER_WAIT_TIMEOUT_SEC", "30"))
_WAIT_SLEEP_SEC = float(os.environ.get("SILENCE_REMOVER_WAIT_SLEEP_SEC", "0.25"))

if _IS_WINDOWS and ctypes:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CreateFileW = _kernel32.CreateFileW
    _CreateFileW.argtypes = [
        wintypes.LPCWSTR,  # lpFileName
        wintypes.DWORD,  # dwDesiredAccess
        wintypes.DWORD,  # dwShareMode
        wintypes.LPVOID,  # lpSecurityAttributes
        wintypes.DWORD,  # dwCreationDisposition
        wintypes.DWORD,  # dwFlagsAndAttributes
        wintypes.HANDLE,  # hTemplateFile
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
    _ERROR_SHARING_VIOLATION = 32
    _ERROR_ACCESS_DENIED = 5
    _ERROR_FILE_NOT_FOUND = 2
    _ERROR_PATH_NOT_FOUND = 3
else:  # pragma: no cover - non-Windows environments
    _kernel32 = None
    _CreateFileW = None
    _CloseHandle = None
    _INVALID_HANDLE_VALUE = None


def _sanitize_filename(name: str) -> str:
    cleaned = "".join(c for c in name if c not in "\0\n\r\t").strip().strip('"').strip("'")
    for ch in ["/", "\\", ":", "*", "?", "\"", "<", ">", "|"]:
        cleaned = cleaned.replace(ch, " ")
    return (" ".join(cleaned.split()) or "untitled")[:200]


def _wait_for_file_release(path: Path, timeout: float = _WAIT_TIMEOUT_SEC) -> bool:
    """On Windows wait until path can be opened for delete access."""
    if not _IS_WINDOWS or not _CreateFileW:
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


def _attempt_rename_with_retries(src: Path, dest: Path) -> bool:
    for attempt in range(1, _RENAME_ATTEMPTS + 1):
        try:
            _wait_for_file_release(src)
            src.replace(dest)
            return True
        except PermissionError as exc:
            if attempt == _RENAME_ATTEMPTS:
                print(
                    f"Rename attempt {attempt}/{_RENAME_ATTEMPTS} failed with permission error: {exc}."
                )
                break
            print(
                f"Rename attempt {attempt}/{_RENAME_ATTEMPTS} failed (permission denied). "
                f"Retrying in {_RENAME_SLEEP_SEC}s..."
            )
            _wait_for_file_release(src)
            time.sleep(_RENAME_SLEEP_SEC)
        except OSError:
            raise
    return False


def _unlink_with_retries(path: Path) -> None:
    for attempt in range(1, _DELETE_ATTEMPTS + 1):
        try:
            _wait_for_file_release(path)
            path.unlink()
            return
        except PermissionError as exc:
            if attempt == _DELETE_ATTEMPTS:
                raise
            if path.exists():
                try:
                    os.chmod(path, path.stat().st_mode | stat.S_IWRITE)
                except OSError:
                    pass
            print(
                f"Failed to remove '{path.name}' (attempt {attempt}/{_DELETE_ATTEMPTS}). "
                f"Retrying in {_DELETE_SLEEP_SEC}s..."
            )
            _wait_for_file_release(path)
            time.sleep(_DELETE_SLEEP_SEC)


def _copy_then_delete(src: Path, dest: Path) -> None:
    if dest.exists():
        _wait_for_file_release(dest)
        dest.unlink()
    shutil.copy2(src, dest)
    print(f"Copied '{src.name}' to '{dest.name}'. Attempting to delete original...")
    try:
        _wait_for_file_release(src)
        _unlink_with_retries(src)
    except PermissionError as exc:
        print(
            f"Could not remove '{src.name}' after copy because it stayed locked "
            f"({exc}). Please close any applications using it and delete manually."
        )
        raise


def rename_single_video_in_place(video_path: Path, temp_dir: Path, output_dir: Path) -> None:
    """Rename a single video in place in output_dir using title from temp_dir."""
    # Resolve to absolute path to ensure file can be found
    video_path = video_path.resolve()
    
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    basename = video_path.stem
    title_file = temp_dir / f"{basename}.title.txt"
    
    new_base: Optional[str] = None
    if title_file.exists():
        raw = title_file.read_text(encoding="utf-8").strip()
        if raw:
            new_base = _sanitize_filename(raw)
    
    if not new_base:
        new_base = _sanitize_filename(basename)
    
    # Check for duplicates in output_dir and append _N suffix if needed
    candidate = new_base
    k = 1
    while (output_dir / f"{candidate}{video_path.suffix}").exists():
        candidate = f"{new_base}_{k}"
        k += 1
    
    dest = output_dir / f"{candidate}{video_path.suffix}"
    dest = dest.resolve()
    
    if video_path == dest:
        print(f"File already has correct name: {video_path.name}")
        return
    
    print(f"Renaming: {video_path.name} -> {dest.name}")
    if _attempt_rename_with_retries(video_path, dest):
        return
    
    print("Rename attempts exhausted. Falling back to copy + delete strategy...")
    _copy_then_delete(video_path, dest)

