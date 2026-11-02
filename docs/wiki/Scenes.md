# Scenes

The *Scenes* tab (the game controller): a different look for the lights while a game or a film is
fullscreen, or while an app you pick is in front. When it's gone, the lights go back to what they
were. Your settings never change: the look sits on top of every strip, the way a keybind does.

## The looks

| | |
| --- | --- |
| *Nothing* | Leave the lights alone (only for "anything fullscreen", so only the apps below get a look) |
| *Off* | Every strip dark |
| *Dimmer* | Whatever the strips show, at a lower brightness (20% to start with) |
| *One colour* | Every LED one colour, picked with the colour wheel, at a brightness |
| *Effect* | One of the animations (Breathing, Comet, Rainbow, ...) on every strip, at a brightness |

*Try it* shows a look for 5 seconds.

## What gets a look

- **Anything fullscreen** gets the look under *When anything is fullscreen*.
- **Apps with their own look:** while one of these is in front, fullscreen or not, it gets its own
  look instead. Type the app's name, or press one of the names Iridia has seen fullscreen, pick a
  look and press *Add* (adding the same app again replaces its look).
- **Never for these:** apps that never get the fullscreen look, a browser playing a video, say.
  Type the name and press *Never for this app*.

An app's name is what the desktop calls its window: `mpv`, `firefox`, `steam_app_1091500` for a
Steam game (the number is the game's Steam ID). Names seen fullscreen show up as buttons, so you
rarely need to type one. Case doesn't matter.

## Timing

| | |
| --- | --- |
| *Comes on after* | How long something has to stay in front before its look comes on (0 to 10 s, 1 s to start with) |
| *Goes back after* | How long after it's gone before the lights go back (0 to 10 s, 2 s): switching away from a game for a moment doesn't make the room flicker |
| *Check every* | Only where the desktop can't tell Iridia by itself (below): how often to look (1 to 30 s) |

## With everything else

A keybind's change to a strip wins over a scene. Notifications still flash on top of a scene. A
scene's brightness still fades when the screen locks and stays under night mode's cap, and the
lights stay dark while the PC sleeps or *lights off* is on.

## How Iridia knows

| Desktop | How | Asked on a timer? |
| --- | --- | --- |
| Hyprland | Its event socket says when the window in front or fullscreen changes | No |
| Sway | Its window events | No |
| KDE Plasma | A small KWin script Iridia loads while scenes are on (nothing is installed; it's gone when they're off) | No |
| X11 (XFCE, Cinnamon, MATE, KDE on X11, i3, ...) | `xprop` on the window in front | Every few seconds as well, for fullscreen switched in place |
| Anything else (GNOME on Wayland, other compositors) | The running programs | Yes, every *Check every* seconds |

On the last row the desktop doesn't tell other apps which window is in front (on GNOME, only an
extension could). Iridia then looks at what's running: an app with its own look gets it while it
runs (a Steam game shows up as `steam_app_N`, a Windows game by its .exe name), and "anything
fullscreen" can't be told. Nothing is watched while scenes are off.

## Command line

```sh
iridia scenes                                  # settings, what's in front, what's showing
iridia scenes on
iridia scenes look dim 20                      # anything fullscreen: off, dim N, color HEX [N], effect NAME [N], none
iridia scenes app mpv off                      # an app's own look ("none" removes it)
iridia scenes app steam_app_1091500 effect embers 80
iridia scenes ignore firefox                   # never for it (unignore to undo)
iridia scenes remove mpv
iridia scenes test                             # show the fullscreen look for 5 s (or: test color ff0000 50)
iridia scenes --on-delay 1 --off-delay 2 --interval 3
```
