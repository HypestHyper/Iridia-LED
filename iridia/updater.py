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
from collections.abc import Callable

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


def _release_info(rel: dict) -> dict | None:
    version = str(rel.get("tag_name") or "").lstrip("v")
    if not version or rel.get("draft"):
        return None
    name = f"iridia-{version}.tar.gz"
    asset = next((a for a in rel.get("assets") or [] if a.get("name") == name), None)
    if asset is None:
        return None
    digest = str(asset.get("digest") or "")
    files = {}                              # every file of the release: the packages too
    for a in rel.get("assets") or []:
        d = str(a.get("digest") or "")
        if a.get("name") and a.get("browser_download_url"):
            files[a["name"]] = {"url": a["browser_download_url"], "size": a.get("size") or 0,
                                "sha256": d[7:].lower() if d.startswith("sha256:") else ""}
    return {"version": version, "files": files, "notes": str(rel.get("body") or "").strip(), "url": asset.get("browser_download_url"),
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

PACKAGE_DIR = "/usr/lib/iridia"           # where the .deb, .rpm and Arch packages put it


def install_kind(venv: str = VENV) -> str:
    """"venv" when this is the install.sh install (updates work), "package" when it came as a system
    package (the package manager updates it), else "source" (a git checkout or a venv of your own:
    update that the way you installed it)."""
    try:
        import sys

        import iridia
        here = os.path.realpath(sys.prefix)
        pkg = os.path.realpath(os.path.dirname(iridia.__file__))
    except Exception:          # noqa: BLE001
        return "source"
    if pkg.startswith(os.path.realpath(PACKAGE_DIR) + os.sep):
        return "package"
    return "venv" if here == os.path.realpath(venv) and os.path.isdir(venv) else "source"


def package_manager() -> str:
    """The command that installs a downloaded package on this system ("" if none is known)."""
    import shutil
    for tool, cmd in (("pacman", "sudo pacman -U ./iridia-*.pkg.tar.zst"), ("apt", "sudo apt install ./iridia_*.deb"),
                      ("dnf", "sudo dnf install ./iridia-*.rpm"), ("zypper", "sudo zypper install ./iridia-*.rpm")):
        if shutil.which(tool):
            return cmd
    return ""


def package_remove_command() -> str:
    """The command that removes the iridia package on this system ("" if none is known)."""
    import shutil
    for tool, cmd in (("pacman", "sudo pacman -R iridia"), ("apt", "sudo apt remove iridia"),
                      ("dnf", "sudo dnf remove iridia"), ("zypper", "sudo zypper remove iridia")):
        if shutil.which(tool):
            return cmd
    return ""


# ------------------------------------------------------------------ system packages

# which package of a release this system takes, and how it installs it (as root)
PACKAGES = {
    "arch": ("iridia-{v}-1-any.pkg.tar.zst", ["pacman", "-U", "--noconfirm"]),
    "deb": ("iridia_{v}-1_all.deb", ["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "install", "-y"]),
    "rpm": ("iridia-{v}-1.noarch.rpm", ["dnf", "install", "-y"]),
    "rpm-zypper": ("iridia-{v}-1.noarch.rpm", ["zypper", "--non-interactive", "install", "--allow-unsigned-rpm"]),
}


def package_format() -> str | None:
    """The kind of package this system installs: arch, deb, rpm or rpm-zypper (None: none known)."""
    import shutil
    for tool, fmt in (("pacman", "arch"), ("apt-get", "deb"), ("dnf", "rpm"), ("zypper", "rpm-zypper")):
        if shutil.which(tool):
            return fmt
    return None


def package_file(info: dict, fmt: str) -> dict | None:
    """The release's package for this system: {name, url, sha256, size}, or None if it has none (or there's
    no release yet: nothing checked)."""
    if not (info or {}).get("version") or fmt not in PACKAGES:
        return None
    name = PACKAGES[fmt][0].format(v=info["version"])
    f = (info.get("files") or {}).get(name)
    return dict(f, name=name) if f else None


def apply_package(info: dict, folder: str = CACHE, log: Callable[[str], None] = print, fmt: str | None = None) -> None:
    """Update a system-package install: the release's package for this system, checked against its SHA-256,
    installed by the package manager as root (pkexec asks for the password the desktop's way), then the
    daemon restarted on the new version."""
    import shutil
    fmt = fmt or package_format()
    if fmt is None:
        raise UpdateError("No package manager this release has a package for (pacman, apt, dnf or zypper).")
    pkg = package_file(info, fmt)
    if pkg is None:
        raise UpdateError(f"Iridia {info['version']} has no {fmt.split('-')[0]} package; install it from its "
                          "release page.")
    if not pkg.get("sha256"):
        raise UpdateError("This package has no checksum to check the download against, so it isn't installed "
                          "automatically. Install it by hand from its release page.")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, pkg["name"])
    log(f"Downloading {pkg['name']}…")
    data = _get(pkg["url"], timeout=120)
    if hashlib.sha256(data).hexdigest() != pkg["sha256"]:
        raise UpdateError("The download doesn't match its checksum (damaged or changed on the way); nothing "
                          "was installed. Try again later.")
    with open(path, "wb") as f:
        f.write(data)
    log("Download checked.")
    cmd = PACKAGES[fmt][1] + [path]
    by_hand = {"arch": "sudo pacman -U", "deb": "sudo apt install", "rpm": "sudo dnf install",
               "rpm-zypper": "sudo zypper install"}[fmt] + f" {path}"
    if os.geteuid() != 0:
        if not shutil.which("pkexec"):
            raise UpdateError("Installing needs your password, and this system has no pkexec to ask for it. "
                              f"Install it yourself: {by_hand}")
        cmd = ["pkexec"] + cmd
    log("Installing (your system asks for your password)…")
    rc = _run(cmd, log)
    if rc in (126, 127) and cmd[0] == "pkexec":
        raise UpdateError("The password prompt was closed, or no password prompt could be shown (on a "
                          "minimal desktop, start a polkit agent). Nothing was installed. Or install it "
                          f"yourself: {by_hand}")
    if rc != 0:
        raise UpdateError(f"The package manager stopped with an error ({rc}); see above. Nothing changed if it "
                          "stopped before installing.")
    log(f"Iridia {info['version']} is installed.")
    exe = shutil.which("iridia") or "/usr/bin/iridia"
    for action in ("stop", "start"):            # the daemon on the new version
        _run([exe, "daemon", action], log)


def reinstall_hint() -> str:
    """How to put the program files back: for the package, reinstall it; else run the installer."""
    if install_kind() == "package":
        return "Reinstall the iridia package (download it again from the release page)."
    return "Run the installer again: bash install.sh"


def prev_version(venv: str = VENV) -> str | None:
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


def can_update_here(info: dict) -> bool:
    """Whether `iridia update` can install this release by itself here (the install.sh copy, or a system
    package with a package for this system's package manager)."""
    kind = install_kind()
    if kind == "venv":
        return bool(info.get("sha256"))
    if kind == "package":
        fmt = package_format()
        return fmt is not None and package_file(info, fmt) is not None
    return False


def notify_with_update(summary: str, body: str, label: str = "Update now") -> int | None:
    """A notification with an Update button; its id (to watch for the button), or None when it couldn't
    be shown that way (a server without gdbus, say)."""
    import re
    import shutil
    if not shutil.which("gdbus"):
        return None
    try:
        r = subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
                            "--object-path", "/org/freedesktop/Notifications",
                            "--method", "org.freedesktop.Notifications.Notify",
                            "Iridia", "0", ICON, summary, body, f"['update', '{label}']",
                            # the notification server's own timeout (-1), like every other notification:
                            # it goes away by itself; the Updates page still has the update after that
                            "{'desktop-entry': <'%s'>, 'urgency': <byte 1>}" % APP_ID, "-1"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"uint32 (\d+)", r.stdout or "")
    return int(m.group(1)) if r.returncode == 0 and m else None


def wait_for_update_button(nid: int, timeout: float = 12 * 3600, stop=None) -> bool:
    """True once the notification's Update button is pressed; False when it's closed, the wait runs out,
    or `stop` (a threading.Event) is set."""
    import re
    import time
    try:
        p = subprocess.Popen(["gdbus", "monitor", "--session", "--dest", "org.freedesktop.Notifications",
                              "--object-path", "/org/freedesktop/Notifications"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    except OSError:
        return False
    import queue
    import threading
    lines: queue.Queue = queue.Queue()

    def read():
        for line in p.stdout:
            lines.put(line)
        lines.put(None)
    threading.Thread(target=read, daemon=True, name="update-button").start()
    end = time.monotonic() + timeout
    pressed = False
    try:
        while time.monotonic() < end and not (stop is not None and stop.is_set()):
            try:
                line = lines.get(timeout=1.0)
            except queue.Empty:
                continue
            if line is None:
                break
            m = re.search(r"ActionInvoked \(uint32 (\d+), '([^']*)'\)", line)
            if m and int(m.group(1)) == nid and m.group(2) == "update":
                pressed = True
                break
            m = re.search(r"NotificationClosed \(uint32 (\d+),", line)
            if m and int(m.group(1)) == nid:
                break
    finally:
        p.terminate()
        try:
            p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            p.kill()
    return pressed


def cli_command() -> str:
    """The `iridia` command of this install."""
    import shutil
    import sys
    here = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "iridia")
    return here if os.path.exists(here) else (shutil.which("iridia") or "/usr/bin/iridia")
