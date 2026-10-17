"""Updates: find a newer release on GitHub, install it, and go back if needed.

Checking asks GitHub's releases API (no account, a few requests a day at most). Updating:
  1. backs up your settings (the caller does that: Settings, Setups and backups),
  2. downloads the release archive and checks it against the SHA-256 GitHub publishes for it,
  3. keeps a copy of the installed version (~/.local/share/iridia-venv.prev),
  4. runs the release's install.sh --update: no questions, no system packages, so no password,
  5. puts the old version back by itself if any of that fails.
"Go back" swaps the kept copy in again.

Only the standard library is used, and everything is imported up front: pip replaces Iridia's own
files while the update runs, so nothing may be imported from them halfway.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

REPO = "HypestHyper/Iridia-LED"
API = os.environ.get("IRIDIA_UPDATE_API") or f"https://api.github.com/repos/{REPO}"
VENV = os.path.expanduser("~/.local/share/iridia-venv")
STATE = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "iridia",
                     "update.json")
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "iridia", "update")
APP_ID = "io.github.HypestHyper.Iridia"     # the launcher's name (iridia/assets.py)
ICON = "iridia"


class UpdateError(Exception):
    """Something the user should read: no network, a bad download, a failed install."""


# ------------------------------------------------------------------ versions

def parse_version(v) -> tuple:
    """'v1.10.2' -> (1, 10, 2); a test version ('1.3.0rc1', '1.3.0-beta') sorts before its release."""
    m = re.match(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)$", str(v or "").strip())
    if not m:
        return (0, 0, 0, 0)
    major, minor, patch, rest = int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0), m.group(4)
    return (major, minor, patch, 0 if rest.strip(".-+ ") else 1)


def newer(candidate, current) -> bool:
    return parse_version(candidate) > parse_version(current)


# ------------------------------------------------------------------ checking

def _get(url: str, timeout: float = 15.0) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "Iridia-updater"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise UpdateError("GitHub is limiting requests from this network right now; try again in an "
                              "hour.") from None
        if e.code == 404:
            raise UpdateError("No releases found.") from None
        raise UpdateError(f"GitHub answered {e.code}.") from None
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise UpdateError(f"Couldn't reach GitHub ({reason}). Are you online?") from None


def _release_info(rel: dict) -> Optional[dict]:
    version = str(rel.get("tag_name") or "").lstrip("v")
    if not version or rel.get("draft"):
        return None
    name = f"iridia-{version}.tar.gz"
    asset = next((a for a in rel.get("assets") or [] if a.get("name") == name), None)
    if asset is None:
        return None
    digest = str(asset.get("digest") or "")
    return {"version": version, "notes": str(rel.get("body") or "").strip(), "url": asset.get("browser_download_url"),
            "sha256": digest[7:].lower() if digest.startswith("sha256:") else "", "size": asset.get("size") or 0,
            "page": rel.get("html_url") or "", "published": str(rel.get("published_at") or "")[:10],
            "prerelease": bool(rel.get("prerelease"))}


def latest(prerelease: bool = False, api: str = API) -> dict:
    """The newest release (test versions only when asked for)."""
    if prerelease:
        rels = json.loads(_get(f"{api}/releases?per_page=15").decode("utf-8"))
    else:
        rels = [json.loads(_get(f"{api}/releases/latest").decode("utf-8"))]
    found = [i for i in (_release_info(r) for r in rels if isinstance(r, dict)) if i]
    if not prerelease:
        found = [i for i in found if not i["prerelease"]]
    if not found:
        raise UpdateError("No release with an Iridia archive found.")
    return max(found, key=lambda i: parse_version(i["version"]))


def load_state() -> dict:
    try:
        with open(STATE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(**changes) -> dict:
    d = dict(load_state(), **changes)
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, STATE)
    except OSError:
        pass
    return d


def check(current: str, prerelease: bool = False, api: str = API) -> dict:
    """{"current", "latest" (or None), "available", "error"}; remembered for the window and the daemon."""
    out = {"current": current, "latest": None, "available": False, "error": None, "checked": int(time.time())}
    try:
        info = latest(prerelease, api)
        out["latest"] = info
        out["available"] = newer(info["version"], current)
    except UpdateError as e:
        out["error"] = str(e)
    except (ValueError, KeyError, TypeError) as e:
        out["error"] = f"GitHub's answer didn't make sense ({type(e).__name__})."
    save_state(last=out)
    return out


# ------------------------------------------------------------------ installing

def install_kind(venv: str = VENV) -> str:
    """"venv" when this is the install.sh install (updates work), else "source" (a git checkout or a
    venv of your own: update that the way you installed it)."""
    try:
        import sys
        here = os.path.realpath(sys.prefix)
    except Exception:          # noqa: BLE001
        return "source"
    return "venv" if here == os.path.realpath(venv) and os.path.isdir(venv) else "source"


def prev_version(venv: str = VENV) -> Optional[str]:
    """The version kept from before the last update, if any."""
    prev = venv + ".prev"
    for d in _glob_dist_info(prev):
        m = re.match(r"^iridia-([^-]+)\.dist-info$", os.path.basename(d))
        if m:
            return m.group(1)
    return None


def _glob_dist_info(venv: str):
    lib = os.path.join(venv, "lib")
    try:
        for py in sorted(os.listdir(lib)):
            sp = os.path.join(lib, py, "site-packages")
            for name in sorted(os.listdir(sp)) if os.path.isdir(sp) else []:
                if name.startswith("iridia-") and name.endswith(".dist-info"):
                    yield os.path.join(sp, name)
    except OSError:
        return


def download(info: dict, folder: str = CACHE, log: Callable[[str], None] = print) -> str:
    """The release archive, checked against GitHub's SHA-256 for it."""
    if not info.get("sha256"):
        raise UpdateError("This release has no checksum to check the download against, so it isn't installed "
                          "automatically. Install it by hand from its release page.")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"iridia-{info['version']}.tar.gz")
    log(f"Downloading Iridia {info['version']}…")
    data = _get(info["url"], timeout=60)
    got = hashlib.sha256(data).hexdigest()
    if got != info["sha256"]:
        raise UpdateError("The download doesn't match its checksum (damaged or changed on the way); nothing "
                          "was installed. Try again later.")
    with open(path, "wb") as f:
        f.write(data)
    log("Download checked.")
    return path


def extract(archive: str, folder: str, version: str) -> str:
    """Unpack the archive (refusing anything that would land outside the folder); returns the source folder."""
    dest = os.path.join(folder, f"src-{version}")
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    root = os.path.realpath(dest)
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        for m in members:
            target = os.path.realpath(os.path.join(dest, m.name))
            if not (target == root or target.startswith(root + os.sep)) or m.issym() or m.islnk() \
                    or m.isdev() or m.isfifo():
                raise UpdateError(f"The archive holds something unexpected ({m.name}); nothing was installed.")
        if hasattr(tarfile, "data_filter"):     # Python 3.8.17+/3.12+: the library checks as well
            tar.extractall(dest, members, filter="data")
        else:
            tar.extractall(dest, members)       # every member checked above
    src = os.path.join(dest, "iridia")
    if not os.path.isfile(os.path.join(src, "install.sh")):
        raise UpdateError("The archive has no install.sh; nothing was installed.")
    with open(os.path.join(src, "pyproject.toml"), encoding="utf-8") as f:
        m = re.search(r'^version = "([^"]+)"', f.read(), re.M)
    if not m or m.group(1) != version:
        raise UpdateError("The archive's version doesn't match the release; nothing was installed.")
    return src


def _run(cmd, log, cwd=None) -> int:
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         text=True, bufsize=1)
    for line in p.stdout:
        log(line.rstrip("\n"))
    return p.wait()


def _daemon(venv: str, action: str, log):
    exe = os.path.join(venv, "bin", "iridia")
    if os.path.exists(exe):
        _run([exe, "daemon", action], log)


def apply(info: dict, venv: str = VENV, folder: str = CACHE, log: Callable[[str], None] = print) -> None:
    """Download, check, keep the current version, install the new one; put the old one back on failure."""
    archive = download(info, folder, log)
    src = extract(archive, folder, info["version"])
    prev = venv + ".prev"
    log("Keeping the installed version, so you can go back…")
    shutil.rmtree(prev, ignore_errors=True)
    shutil.copytree(venv, prev, symlinks=True)
    log(f"Installing Iridia {info['version']}…")
    rc = _run(["bash", os.path.join(src, "install.sh"), "--update"], log, cwd=src)
    if rc != 0:
        log("The install failed: putting the previous version back…")
        _daemon(venv, "stop", log)
        shutil.rmtree(venv, ignore_errors=True)
        shutil.copytree(prev, venv, symlinks=True)
        _daemon(venv, "start", log)
        raise UpdateError(f"Installing {info['version']} failed (see the output above); the previous version "
                          "is back. Your settings were not changed.")
    shutil.rmtree(os.path.dirname(src), ignore_errors=True)
    try:
        os.remove(archive)
    except OSError:
        pass
    save_state(last=None, installed=info["version"], installed_at=int(time.time()))
    log(f"Iridia {info['version']} is installed.")


def rollback(venv: str = VENV, log: Callable[[str], None] = print) -> str:
    """Swap the kept version in again; the one it replaces is kept in turn (so this can be undone)."""
    prev = venv + ".prev"
    version = prev_version(venv)
    if not version or not os.path.isdir(prev):
        raise UpdateError("There's no previous version to go back to.")
    _daemon(venv, "stop", log)
    swap = venv + ".swap"
    shutil.rmtree(swap, ignore_errors=True)
    os.rename(venv, swap)
    os.rename(prev, venv)
    os.rename(swap, prev)
    _daemon(venv, "start", log)
    log(f"Back on Iridia {version}.")
    return version


# ------------------------------------------------------------------ telling the user

def notify(summary: str, body: str) -> bool:
    """A desktop notification (any desktop with a notification server: GNOME, KDE, XFCE, Cinnamon, MATE,
    mako, dunst, swaync, ...). Clicking it opens Iridia where the server supports that."""
    if shutil.which("gdbus"):
        r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
                            "--object-path", "/org/freedesktop/Notifications",
                            "--method", "org.freedesktop.Notifications.Notify",
                            "Iridia", "0", ICON, summary, body, "[]",
                            "{'desktop-entry': <'%s'>, 'urgency': <byte 1>}" % APP_ID, "-1"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        if r.returncode == 0:
            return True
    if shutil.which("notify-send"):
        r = subprocess.run(["notify-send", "--app-name=Iridia", f"--icon={ICON}", summary, body],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        return r.returncode == 0
    return False
