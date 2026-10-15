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
| `gui.json` | Window preferences: font, reduce motion, language, recently used colors |
| `setups/` | Saved setups; automatic backups in `setups/.backups/` |
| `detection_cache.json` | Which wallpaper tool was found last |

### gui.json: language

`"language"` picks the window's language. Leave it out (or set `""`) for the default, Proper English
(British spelling). Values: `"en_GB"` (Proper English), `"en"` (American English), `"en_posh"`
(Posh English), `"en_pirate"` (Pirate) and `"fr_omelette"` (Français). The same choice is in
Settings, Appearance, Language; it applies when the window restarts. The command line and the log
always use American spelling.

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
| `openrgb.port` | `null` | Its port; `null` finds it on 6742 to 6744 |
| `openrgb.start_server` | `true` | Start OpenRGB's server when it isn't reachable on this machine (see [Installation](Installation.md#setting-up-openrgb)) |
| `openrgb.server_command` | `""` | The command that runs OpenRGB's server; empty finds `openrgb` or the Flatpak |
| `openrgb.auto_restart_on_missing_device` | `true` | Restart OpenRGB's server when a device goes missing (at most twice per device) |
| `openrgb.missing_device_restart_threshold_sec` | `45` | How long a device must be missing first |
| `openrgb.restart_cooldown_sec` | `120` | Minimum time between such restarts |
| `ddc.enabled` | `true` | Follow monitor brightness |
| `ddc.bus_number` | `null` | The I2C bus of the monitor; `null` finds it |
| `ddc.fallback_brightness` | `100` | Brightness used when no monitor answers |
| `night.enabled`, `night.start`, `night.end`, `night.cap` | `false`, `23:00`, `07:00`, `20` | Night mode |
| `sleep.lights_off` | `true` | LEDs off while the PC sleeps |
| `logging.enabled` | `false` | Write a log file |
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
| `ma_per_led` | Current per LED at full white for the power estimate (default 60) |

New devices are added automatically the first time OpenRGB reports them. Zones OpenRGB reports with no
size yet are added switched off and switch on once they have a size.
