# Configuration

Everything can be changed in the window, and that's the recommended way. The settings are plain files
in `~/.config/iridia/` if you want to read, back up or edit them by hand. The daemon notices changes to
`config.json` and `palette.json` and reloads them.

## Files

| File | Contents |
| --- | --- |
| `config.json` | Devices and zones, wallpaper and color settings, OpenRGB, DDC, night mode, sleep, logging, timing |
| `layout.json` | The Layout tab: where each strip is, bends, clones, hidden strips, the view |
| `palette.json` | The 48 color palette for Palette mode |
| `calibration/*.json` | Calibration profiles, one file each (`WS2812B.json`, `Neutral.json`, your own) |
| `custom_colors.json` | Your saved colors, and which colors are exact |
| `wallpaper_colors.json` | Extracted colors per wallpaper (a cache) and your color picks per wallpaper and zone |
| `gui.json` | Window preferences: font, size, window buttons, reduce motion, language, recently used colors |
| `setups/` | Saved setups; automatic backups in `setups/.backups/` |
| `detection_cache.json` | Which wallpaper tool was found last |

### gui.json: language

`"language"` picks the window's language. Leave it out (or set `""`) for the default, British spelling
(`"en_GB"`); `"en"` gives American English. The same choice is in Settings, Appearance, Language; it
applies when the window restarts. The command line and the log always use American spelling.

### gui.json: ui_size

`"ui_size"` is the window's size: `"auto"` (default: `"default"`, or `"compact"` in a window narrower
than 900 pixels), `"compact"`, `"default"` or `"large"`. Settings, Appearance, Size, and Ctrl+minus,
Ctrl+plus and Ctrl+0 in the window, change it.

### gui.json: window_buttons

`"window_buttons": false` hides the window's own minimize, maximize and close buttons (Settings,
Appearance, Window buttons). They're shown by default, on the side and in the order your desktop's
`gtk-decoration-layout` asks for (GNOME's default shows only close).

Logs go to `~/.local/share/iridia/iridia.log` when file logging is on. The daemon's socket is
`$XDG_RUNTIME_DIR/iridia-UID.sock`.

A broken `config.json` (invalid JSON) is moved aside to `config.json.bak` and replaced with defaults,
and the log says so. Values of the wrong type are replaced with their defaults one by one.

## config.json: general settings

| Key | Default | Meaning |
| --- | --- | --- |
| `wallpaper.manual_path` | `null` | Always use this image instead of detecting the wallpaper |
| `wallpaper.watch_folder` | `~/Pictures/Wallpapers` | Fallback: the newest image in this folder (and two levels of subfolders) |
| `color.backend` | `auto` | Color engine: `auto`, `material` or `pillow` (see [How it works](How-It-Works.md#color-engines)) |
| `color.frozen` | `false` | Freeze the current colors |
| `openrgb.host` | `127.0.0.1` | Where the OpenRGB SDK server runs |
| `openrgb.port` | `null` | Its port; `null` finds it on 6742 to 6744. The OpenRGB Iridia starts listens on it |
| `openrgb.start_method` | `daemon` | What starts OpenRGB's server: `daemon`, `systemd` or `off` (see [Installation](Installation.md#setting-up-openrgb)). Replaces 1.1.0's `openrgb.start_server` (`false` there becomes `off`) |
| `openrgb.server_command` | `""` | The command that runs OpenRGB's server; empty finds `openrgb` or the Flatpak |
| `openrgb.auto_restart_on_missing_device` | `true` | Restart OpenRGB's server when a device goes missing (at most twice per device; only an OpenRGB Iridia started) |
| `openrgb.missing_device_restart_threshold_sec` | `45` | How long a device must be missing first |
| `openrgb.restart_cooldown_sec` | `120` | Minimum time between such restarts |
| `ddc.enabled` | `true` | Follow monitor brightness |
| `ddc.bus_number` | `null` | The I2C bus of the monitor; `null` finds it |
| `ddc.fallback_brightness` | `100` | Brightness used when no monitor answers |
| `night.enabled`, `night.start`, `night.end`, `night.cap` | `false`, `23:00`, `07:00`, `20` | Night mode |
| `sleep.lights_off` | `true` | LEDs off while the PC sleeps |
| `animations.enabled` | `true` | Run animated effects (off: animated zones show their first color) |
| `animations.fps` | `30` | Frames per second: 15, 30 or 60 |
| `animations.night_pause`, `animations.night_slow` | `false`, `false` | Pause or slow (half speed) animations in night mode |
| `logging.enabled` | `false` | Write a log file. A daemon started outside systemd (where there's no journal) turns it on the first time, unless you've set it yourself |
| `logging.file_path` | `~/.local/share/iridia/iridia.log` | Where |
| `logging.level` | `info` | `debug`, `info`, `warning` or `error` |
| `logging.max_size_kb` | `1024` | The log file is kept under this size (the oldest lines drop off) |
| `timing.ddc_poll_interval_sec` | `5` | How often the monitor's brightness is read |
| `timing.openrgb_retry_interval_sec` | `5` | How often to retry connecting to OpenRGB |
| `timing.device_enumeration_interval_sec` | `10` | How often to look for new or missing devices |
| `timing.wallpaper_debounce_ms` | `300` | Ignore repeated file events within this time |

## config.json: devices and zones

`devices` holds one entry per OpenRGB device, keyed by its name. A device with zones has a `zones` object
with one entry per zone; a device without zones keeps the zone settings on itself.

```json
"devices": {
  "ASUS TUF GAMING B550M-E": {
    "enabled": true,
    "zones": {
      "Aura Addressable 1": {
        "enabled": true,
        "display_name": "Desk back",
        "led_count": 60,
        "pattern": "gradient",
        "pattern_colors": [0, 1, "ff8800"],
        "pattern_params": {"stops": [0.0, 0.5, 1.0], "reverse": false},
        "mode": "calibrated",
        "calibration_profile": "WS2812B",
        "brightness_sync": true,
        "brightness_range": [10, 100],
        "strip_type": "addressable",
        "color_order": "RGB",
        "power_limit": 4.0
      }
    }
  }
}
```

| Zone key | Meaning |
| --- | --- |
| `enabled` | Zone on or off |
| `display_name` | Your name for it |
| `led_count` | LEDs Iridia sends to |
| `pattern` | `solid`, `gradient`, `segments`, `center_out`, `edges_in`, `alternating`, `paint` |
| `pattern_colors` | Numbers are wallpaper colors (0 is the first), strings are fixed hex colors |
| `pattern_params` | `stops` (color stop positions 0 to 1), `reverse`, `mirror`, `paint` (one hex or `null` per LED) |
| `mode` | Color correction: `full` (Off), `palette`, `calibrated` |
| `calibration_profile` | Profile name for Calibrated |
| `brightness_sync` | Follow the monitor |
| `manual_brightness` | 0 to 100, used when not following |
| `brightness_range` | `[min, max]` the monitor's brightness is mapped onto |
| `invert_brightness` | Bias lighting |
| `gamma_correction`, `gamma_value` | Gamma on/off and its value (default 2.2) |
| `strip_type` | `addressable`, `addressable12`, `single`, `rgbw`; missing means automatic |
| `color_order` | `RGB`, `RBG`, `GRB`, `GBR`, `BRG`, `BGR` |
| `leds_per_pixel` | For 12V grouped strips (drawing only) |
| `power_limit` | Amps, `0` for none |
| `animation` | An animated effect, or missing/`null` for the static pattern: `{"effect": "breathing", "speed": 4, "min": 10, "max": 100, ...}`. Every effect's settings are listed in [Animations](Animations.md); values out of range are clamped, unknown ones ignored |
| `ma_per_led` | Current per LED at full white for the power estimate (default 60) |
| `sections` | The strip's parts, missing or `[]` when it isn't split: `[{"start": 0, "type": "same"}, {"start": 27, "type": "pattern", "pattern": "gradient", "colors": [0, "ff0000"], "params": {"stops": [...]}}, {"start": 54, "type": "effect", "animation": {"effect": "comet", ...}, "colors": [1]}, {"start": 70, "type": "off"}]`. `start` is the part's first LED, counted from 0 |
| `led_overrides` | Single LEDs set by hand, over everything else: `{"26": "ffffff", "53": "000000"}` (LED counted from 0, `000000` is off) |

New devices are added automatically the first time OpenRGB reports them. Zones OpenRGB reports with no
size yet are added switched off and switch on once they have a size.
