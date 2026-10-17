# Updates

Iridia can update itself from its [GitHub releases](https://github.com/HypestHyper/Iridia-LED/releases).
It works for the usual install (the one `install.sh` makes in `~/.local/share/iridia-venv`). If you run
Iridia from a git checkout or a virtualenv of your own, update it the way you installed it
(`git pull`, then `bash install.sh`).

## In the window

The **Updates** tab shows the version you have, whether a newer one exists, and what's new in it:

| Button | What it does |
| --- | --- |
| **Check now** | Ask GitHub right away |
| **Update now** | Install the new version (see below); the window restarts by itself when it's done |
| **Skip this version** | No more notifications for this one; newer versions still show up |
| **Go back to …** | Put the version from before the last update back |

The tab's icon lights up while there's something to install.

| Setting | Default | |
| --- | --- | --- |
| Look for updates when Iridia starts | on | The daemon asks once per start (a minute after it starts), the window when it opens; at most every few hours |
| Show a notification when there's a new version | on | One desktop notification per new version |
| Include test versions | off | Also offer releases marked as pre-releases |

Checking sends nothing about you: it's one request to GitHub's public releases API.

## What an update does

1. Backs up your settings (it shows up under Settings, *Setups and backups*, as "before updating to …").
2. Downloads the release archive and checks it against the SHA-256 checksum GitHub publishes for it. A
   damaged or changed download is refused and nothing is installed.
3. Keeps a copy of the version you have now (`~/.local/share/iridia-venv.prev`).
4. Runs the release's `install.sh --update`: no questions and no system packages, so **no password**,
   and how OpenRGB and the daemon start stays as you set it.
5. If anything goes wrong, puts the previous version back by itself and starts the daemon again.

The LEDs pause for a few seconds while the daemon restarts.

## Going back

**Go back to …** (or `iridia update --rollback`) swaps the kept version in. The version you had is kept in
its place, so you can switch again. Your settings are not touched; to undo settings too, restore the
backup from before the update under *Setups and backups*.

## From the command line

```bash
iridia update --check       # is there a new version?
iridia update               # show what's new, ask, then install it
iridia update --yes         # without asking
iridia update --rollback    # back to the version before the last update
iridia update --prerelease  # include test versions
```

## Notifications

The daemon sends the notification through the desktop's notification service (GNOME, KDE, XFCE,
Cinnamon, MATE, Budgie, COSMIC, and on tiling compositors mako, dunst, swaync, fnott, ...), using
`gdbus`, or `notify-send` when `gdbus` isn't there. Without a notification service the Updates tab still
shows it.
