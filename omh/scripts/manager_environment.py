"""Manage only the current user's omh PATH entry; never edit system profiles."""
from __future__ import annotations

import json
import os
import shlex
import stat
import tempfile
from pathlib import Path

START = "# oh-my-harness PATH"
RECEIPT = "environment.json"


def _ordinary(path: Path, *, directory: bool = False) -> None:
    """Reject links/reparse points for manager-owned state, including broken links."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    reparse = getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if reparse or not expected:
        raise RuntimeError(f"expected an ordinary {'directory' if directory else 'file'}: {path}")


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _receipt_path(home: Path) -> Path:
    _ordinary(home, directory=True)
    _ordinary(home / "state", directory=True)
    path = home / "state" / RECEIPT
    _ordinary(path)
    return path


def _load_receipt(home: Path) -> dict:
    path = _receipt_path(home)
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("product") != "oh-my-harness":
        raise RuntimeError(f"unrecognized PATH receipt: {path}")
    return payload


def _block(bin_dir: str, *, fish: bool = False) -> str:
    if "\n" in bin_dir or "\r" in bin_dir or ":" in bin_dir:
        raise ValueError("POSIX PATH entry cannot contain a colon or a newline")
    if fish:
        quoted = "'" + bin_dir.replace("\\", "\\\\").replace("'", "\\'") + "'"
        body = f"if not contains -- {quoted} $PATH\n    set -gx PATH {quoted} $PATH\nend"
    else:
        quoted = shlex.quote(bin_dir)
        body = (f'case ":${{PATH:-}}:" in\n'
                f"    *:{quoted}:*) ;;\n"
                f'    *) export PATH={quoted}${{PATH:+:"$PATH"}} ;;\n'
                "esac")
    return f"{START}\n{body}\n"


def _replace_block(text: str, block: str | None, allowed: set[str]) -> str:
    """Replace our exact block, preserving every byte outside it."""
    starts = text.count(START)
    if starts == 0:
        if block is None:
            return text
        return text + ("\n" if text and not text.endswith("\n") else "") + block
    if starts != 1:
        raise RuntimeError("PATH markers are duplicated; preserve the profile and inspect its managed block")
    begin = text.index(START)
    if begin and text[begin - 1] != "\n":
        raise RuntimeError("PATH marker is not on its own line")
    if text[begin:].rstrip("\n") == START:
        raise RuntimeError("PATH block is incomplete; preserve the profile and inspect its managed block")
    # The complete known command bounds ownership without a closing marker.
    for expected in allowed:
        expected = expected.rstrip("\n")
        finish = begin + len(expected)
        if text.startswith(expected, begin) and (finish == len(text) or text[finish] == "\n"):
            if finish < len(text):
                finish += 1
            return text[:begin] + (block or "") + text[finish:]
    raise RuntimeError("managed PATH block was edited or belongs to another installation; no profile content was overwritten")


def _profile_paths(user_home: Path) -> list[tuple[Path, bool]]:
    """Register only the active shell's own config, never login profiles."""
    result = []
    shell = Path(os.environ.get("SHELL", "/bin/bash")).name
    if shell == "bash":
        result.append((user_home / ".bashrc", False))
    elif shell == "zsh":
        root = Path(os.environ.get("ZDOTDIR") or user_home).expanduser()
        if not root.is_absolute():
            raise ValueError("ZDOTDIR must be absolute")
        result.append((root / ".zshrc", False))
    elif shell == "fish":
        root = Path(os.environ.get("XDG_CONFIG_HOME") or user_home / ".config").expanduser()
        if not root.is_absolute():
            raise ValueError("XDG_CONFIG_HOME must be absolute")
        result.append((root / "fish" / "conf.d" / "oh-my-harness.fish", True))
    return result


def _windows_key(value: str) -> str:
    import ntpath
    return ntpath.normcase(ntpath.normpath(os.path.expandvars(value.strip().strip('"'))))


def _windows_path(value: str, entry: str, *, remove: bool = False) -> tuple[str, bool]:
    parts = value.split(";") if value else []
    found = any(_windows_key(part) == _windows_key(entry) for part in parts)
    if remove:
        return ";".join(part for part in parts if _windows_key(part) != _windows_key(entry)), found
    return (value, False) if found else (";".join([entry, *parts]), True)


def _broadcast_windows_environment() -> None:
    import ctypes
    from ctypes import wintypes
    result = ctypes.c_size_t()
    send = ctypes.windll.user32.SendMessageTimeoutW
    send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR,
                     wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
    send.restype = wintypes.LPARAM
    # Notify Explorer; running terminal processes still retain their own environment.
    send(0xFFFF, 0x001A, 0, "Environment", 0x0002, 2000, ctypes.byref(result))


def ensure_user_path(home: Path, *, dry_run: bool = False, remove: bool = False) -> None:
    """Persist PATH idempotently; removing never removes a pre-existing user entry."""
    home = Path(os.path.abspath(home.expanduser()))
    user_home = Path.home()
    receipt = _load_receipt(home)
    entry = str(home / "bin")
    same_user = receipt.get("userHome") == str(user_home)
    previous = receipt.get("bin")
    # The recorded bin supports relocation; another account's paths are not write targets.
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ) as key:
                try:
                    value, kind = winreg.QueryValueEx(key, "Path")
                except FileNotFoundError:
                    value, kind = "", winreg.REG_EXPAND_SZ
        except FileNotFoundError:
            value, kind = "", winreg.REG_EXPAND_SZ
        if not isinstance(value, str) or kind not in {winreg.REG_SZ, winreg.REG_EXPAND_SZ}:
            raise RuntimeError("current-user Path is not a string registry value")
        updated = value
        owned = bool(same_user and receipt.get("added"))
        if owned and isinstance(previous, str) and (remove or previous != entry):
            updated, _ = _windows_path(updated, previous, remove=True)
        added = owned and previous == entry
        if not remove:
            updated, inserted = _windows_path(updated, entry)
            added = added or inserted
        if updated != value:
            print(f"{'would update' if dry_run else 'update'} current-user PATH")
            if not dry_run:
                with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
                    winreg.SetValueEx(key, "Path", 0, kind, updated)
                _broadcast_windows_environment()
        new_receipt = {"product": "oh-my-harness", "userHome": str(user_home), "bin": entry, "added": added}
    else:
        paths = _profile_paths(user_home)
        # Retain same-user ownership even for external ZDOTDIR/XDG_CONFIG_HOME.
        # Prior-only paths are cleanup targets, never destinations for new blocks.
        # A receipt copied from another account is not a filesystem write list.
        known = {str(path): (path, fish) for path, fish in paths}
        active_profiles = set(known)
        if same_user:
            for item in receipt.get("profiles", []):
                if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                    continue
                path = Path(item["path"])
                if path.is_absolute():
                    known.setdefault(str(path), (path, bool(item.get("fish"))))
        plans = []
        for path, fish in known.values():
            # Resolve dotfile symlinks instead of replacing the symlink itself.
            target = path.resolve(strict=False)
            if target.exists() and not target.is_file():
                raise RuntimeError(f"shell profile is not a file: {path}")
            old = target.read_bytes().decode("utf-8") if target.exists() else ""
            current_block = _block(entry, fish=fish)
            entries = {entry, previous} if isinstance(previous, str) else {entry}
            allowed = {_block(value, fish=fish) for value in entries}
            cleanup_only = remove or str(path) not in active_profiles
            new = _replace_block(old, None if cleanup_only else current_block, allowed)
            plans.append((path, target, old, new, fish))
        # Preflight every profile before modifying any of them.
        for path, target, old, new, fish in plans:
            if old != new:
                print(f"{'would update' if dry_run else 'update'} PATH profile: {path}")
                if not dry_run:
                    _atomic_text(target, new)
        new_receipt = {
            "product": "oh-my-harness", "userHome": str(user_home), "bin": entry,
            "profiles": [{"path": str(path), "fish": fish} for path, _, _, _, fish in plans
                         if str(path) in active_profiles],
        }
    if dry_run:
        return
    path = _receipt_path(home)
    if remove:
        path.unlink(missing_ok=True)
    else:
        serialized = json.dumps(new_receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if not path.exists() or path.read_text(encoding="utf-8") != serialized:
            _atomic_text(path, serialized)
        current = os.environ.get("PATH", "")
        if entry not in current.split(os.pathsep):
            os.environ["PATH"] = entry + (os.pathsep + current if current else "")
        if os.name == "nt" or new_receipt["profiles"]:
            print("omh is registered for new terminals; existing parent shells keep their current PATH.")
        else:
            print("No supported shell config was selected; PATH was not registered for new terminals.")
