# Scenes

The *Scenes* tab (the game controller): a different look for the lights while a game or a film is
fullscreen, or while an app you pick is in front. When it's gone, the lights go back to what they
were. Your settings never change: the look sits on top of the strips, the way a keybind does.

## Scenes

Make as many as you like, each "when this happens, these strips look like this". *New scene*:

| | |
| --- | --- |
| Name | *Games*, *Films*, ... |
| When | *Anything fullscreen*, or *These apps*: while one of them is in front, fullscreen or not |
| Which strips | *Everything*, or the strips you tick |
| What they do | *Off*, *Dimmer* (20% to start with), *One colour* at a brightness, or an *Effect* (Breathing, Comet, Rainbow, ...) at a brightness. *Try it* shows it for 5 seconds |

In the list, each scene has a switch (off keeps it for later), ˄ ˅ to move it, ▶ to try it and the
pencil to change or delete it. Where two scenes want the same strip at once (a game in its own
scene that is also fullscreen), the one higher up wins; a new scene for apps goes above the ones for
anything fullscreen. *On now* marks the scenes showing.

*Use scenes* at the top switches them all on or off. To start with there's one scene, *Anything
fullscreen*, dimming everything to 20%. Scenes from before (one look for anything fullscreen and a
look per app) become scenes of their own.

An app's name is what the desktop calls its window: `mpv`, `firefox`, `steam_app_1091500` for a
Steam game (the number is the game's Steam ID). Names seen fullscreen show up as buttons in the
editor, so you rarely need to type one. Case doesn't matter.

**Never for these:** apps that never count as fullscreen, a browser playing a video, say.

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
fullscreen" can't be told. Nothing is watched while scenes are off (or none is switched on).

## Command line

```sh
iridia scenes                                  # your scenes (* = showing), what's in front
iridia scenes on
iridia scenes look dim 20                      # the "anything fullscreen" scene: off, dim N, color HEX [N], effect NAME [N], none
iridia scenes app mpv off                      # a scene for one app ("none" removes it)
iridia scenes app steam_app_1091500 effect embers 80
iridia scenes ignore firefox                   # never counts as fullscreen (unignore to undo)
iridia scenes remove mpv                       # takes the app out of its scenes
iridia scenes test                             # show the fullscreen scene for 5 s (or: test color ff0000 50)
iridia scenes --on-delay 1 --off-delay 2 --interval 3
```
