"""Where Iridia keeps its socket, lock and pid files: a folder only this user can use.

XDG_RUNTIME_DIR when it's set; else /run/user/UID if it's there and ours (cron, `sudo -u`, some SSH
sessions don't set the variable); else ~/.cache/iridia/run. Never the shared /tmp, where another
user could put a file or socket of their own under the name Iridia expects first.
"""
import os
import stat


def _private(path: str) -> bool:
    """A real folder (not a link), owned by this user, that nobody else can write to."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & 0o022


def runtime_dir() -> str:
    env = os.environ.get("XDG_RUNTIME_DIR")
    if env:
        return env
    run = f"/run/user/{os.getuid()}"
    if _private(run):
        return run
    path = os.path.join(os.path.expanduser("~"), ".cache", "iridia", "run")
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def runtime_path(name: str) -> str:
    return os.path.join(runtime_dir(), name)
