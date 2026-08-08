"""Tkinter dialogs for the Iridia tray GUI."""

import json
import os
import tkinter as tk
from tkinter import ttk, colorchooser, messagebox, filedialog
from typing import Callable, List, Optional

from iridia.client import Client
from iridia.palette import Palette


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb(hex_color: str) -> tuple:
    return int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"{r:02x}{g:02x}{b:02x}"


class DualRangeSlider(tk.Canvas):
    """Custom dual-handle range slider (0-100) for brightness range."""

    def __init__(self, parent, min_val=0, max_val=100, on_change=None, **kwargs):
        super().__init__(parent, width=300, height=40, highlightthickness=0, **kwargs)
        self.min_val = min_val
        self.max_val = max_val
        self.on_change = on_change
        self._dragging = None

        # Draw track
        self.create_line(20, 20, 280, 20, width=4, fill="#444", capstyle=tk.ROUND)
        self._active_line = self.create_line(20, 20, 280, 20, width=4, fill="#00aa66", capstyle=tk.ROUND)

        # Handles
        self._min_handle = self.create_oval(0, 0, 0, 0, fill="#00aa66", outline="", width=0)
        self._max_handle = self.create_oval(0, 0, 0, 0, fill="#00aa66", outline="", width=0)

        # Labels
        self._min_label = self.create_text(0, 0, text="", fill="white", font=("", 9))
        self._max_label = self.create_text(0, 0, text="", fill="white", font=("", 9))

        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

        self._update_handles()

    def _pos_to_val(self, x):
        x = max(20, min(280, x))
        return int((x - 20) / 260 * 100)

    def _val_to_pos(self, v):
        return 20 + (v / 100) * 260

    def _update_handles(self):
        x1 = self._val_to_pos(self.min_val)
        x2 = self._val_to_pos(self.max_val)

        self.coords(self._min_handle, x1 - 8, 12, x1 + 8, 28)
        self.coords(self._max_handle, x2 - 8, 12, x2 + 8, 28)
        self.coords(self._active_line, x1, 20, x2, 20)
        self.coords(self._min_label, x1, 35)
        self.coords(self._max_label, x2, 35)
        self.itemconfig(self._min_label, text=f"{self.min_val}%")
        self.itemconfig(self._max_label, text=f"{self.max_val}%")

    def _on_click(self, event):
        x1 = self._val_to_pos(self.min_val)
        x2 = self._val_to_pos(self.max_val)
        d1 = abs(event.x - x1)
        d2 = abs(event.x - x2)
        if d1 < d2:
            self._dragging = "min"
        else:
            self._dragging = "max"
        self._on_drag(event)

    def _on_drag(self, event):
        if not self._dragging:
            return
        v = self._pos_to_val(event.x)
        if self._dragging == "min":
            self.min_val = min(v, self.max_val - 1)
        else:
            self.max_val = max(v, self.min_val + 1)
        self._update_handles()
        if self.on_change:
            self.on_change(self.min_val, self.max_val)

    def _on_release(self, event):
        self._dragging = None

    def get(self):
        return self.min_val, self.max_val

    def set(self, min_val, max_val):
        self.min_val = max(0, min(100, min_val))
        self.max_val = max(0, min(100, max_val))
        self._update_handles()


# ---------------------------------------------------------------------------
# Device Dialog
# ---------------------------------------------------------------------------

class DeviceDialog:
    """Settings dialog for a single OpenRGB device."""

    PATTERNS = ["solid", "gradient", "segments", "center_out", "edges_in", "alternating"]

    def __init__(self, device_name: str, device_config: dict, client: Client, on_save: Callable):
        self.device_name = device_name
        self.cfg = device_config
        self.client = client
        self.on_save = on_save

        self.win = tk.Toplevel()
        self.win.title(f"Iridia — {device_name}")
        self.win.geometry("420x520")
        self.win.resizable(False, False)
        self.win.configure(bg="#1e1e1e")

        self._build()

    def _build(self):
        c = self.cfg
        pad = {"padx": 15, "pady": 5}

        # Title
        tk.Label(self.win, text=self.device_name, bg="#1e1e1e", fg="white",
                 font=("", 14, "bold")).pack(pady=(15, 5))

        # Enabled
        self._enabled = tk.BooleanVar(value=c.get("enabled", True))
        tk.Checkbutton(self.win, text="Enabled", variable=self._enabled,
                       bg="#1e1e1e", fg="white", selectcolor="#333",
                       activebackground="#1e1e1e", activeforeground="white").pack(anchor="w", **pad)

        # Mode
        frame = tk.Frame(self.win, bg="#1e1e1e")
        frame.pack(anchor="w", fill="x", **pad)
        tk.Label(frame, text="Mode:", bg="#1e1e1e", fg="white").pack(side="left")
        self._mode = ttk.Combobox(frame, values=["palette", "full"], state="readonly", width=12)
        self._mode.set(c.get("mode", "palette"))
        self._mode.pack(side="left", padx=10)

        # Pattern
        frame = tk.Frame(self.win, bg="#1e1e1e")
        frame.pack(anchor="w", fill="x", **pad)
        tk.Label(frame, text="Pattern:", bg="#1e1e1e", fg="white").pack(side="left")
        self._pattern = ttk.Combobox(frame, values=self.PATTERNS, state="readonly", width=15)
        self._pattern.set(c.get("pattern", "solid"))
        self._pattern.pack(side="left", padx=10)

        # LED Count per zone
        zones = c.get("zones", {})
        if zones:
            tk.Label(self.win, text="LED Count per Zone:", bg="#1e1e1e", fg="white",
                     font=("", 10, "bold")).pack(anchor="w", **pad)
            self._zone_counts = {}
            for zname, zcfg in zones.items():
                frame = tk.Frame(self.win, bg="#1e1e1e")
                frame.pack(anchor="w", fill="x", padx=30, pady=2)
                tk.Label(frame, text=f"{zname}:", bg="#1e1e1e", fg="#aaa").pack(side="left")
                var = tk.StringVar(value=str(zcfg.get("led_count", 48)))
                self._zone_counts[zname] = var
                tk.Spinbox(frame, from_=1, to=300, textvariable=var, width=6).pack(side="left", padx=10)

        # Brightness Range Slider
        tk.Label(self.win, text="Brightness Range:", bg="#1e1e1e", fg="white",
                 font=("", 10, "bold")).pack(anchor="w", **pad)
        br = c.get("brightness_range", [0, 100])
        self._range_slider = DualRangeSlider(self.win, min_val=br[0], max_val=br[1])
        self._range_slider.pack(anchor="w", padx=15, pady=5)
        tk.Label(self.win, text="Drag left handle to 0 to allow LEDs to turn off.",
                 bg="#1e1e1e", fg="#888", font=("", 8)).pack(anchor="w", padx=15)

        # Brightness Sync
        self._sync = tk.BooleanVar(value=c.get("brightness_sync", True))
        tk.Checkbutton(self.win, text="Sync with monitor brightness (DDC/CI)", variable=self._sync,
                       bg="#1e1e1e", fg="white", selectcolor="#333",
                       activebackground="#1e1e1e", activeforeground="white").pack(anchor="w", **pad)

        # Manual Brightness (when sync is off)
        frame = tk.Frame(self.win, bg="#1e1e1e")
        frame.pack(anchor="w", fill="x", **pad)
        tk.Label(frame, text="Manual brightness:", bg="#1e1e1e", fg="white").pack(side="left")
        self._manual = tk.StringVar(value=str(c.get("manual_brightness", 100)))
        tk.Spinbox(frame, from_=0, to=100, textvariable=self._manual, width=5).pack(side="left", padx=10)

        # Invert
        self._invert = tk.BooleanVar(value=c.get("invert_brightness", False))
        tk.Checkbutton(self.win, text="Invert sync (bias lighting mode)", variable=self._invert,
                       bg="#1e1e1e", fg="white", selectcolor="#333",
                       activebackground="#1e1e1e", activeforeground="white").pack(anchor="w", **pad)

        # Gamma
        self._gamma = tk.BooleanVar(value=c.get("gamma_correction", False))
        tk.Checkbutton(self.win, text="Apply gamma correction (γ=2.2)\nMakes low-brightness colors more accurate on cheap strips",
                       variable=self._gamma, bg="#1e1e1e", fg="white", selectcolor="#333",
                       activebackground="#1e1e1e", activeforeground="white").pack(anchor="w", **pad)

        # Buttons
        frame = tk.Frame(self.win, bg="#1e1e1e")
        frame.pack(pady=15)
        tk.Button(frame, text="Save", command=self._save, bg="#00aa66", fg="white",
                  activebackground="#008844", width=10).pack(side="left", padx=5)
        tk.Button(frame, text="Cancel", command=self.win.destroy, bg="#444", fg="white",
                  activebackground="#333", width=10).pack(side="left", padx=5)

    def _save(self):
        # Update config via IPC
        self.client.set_device(self.device_name, self._enabled.get())
        self.client.set_mode(self.device_name, self._mode.get())
        self.client.set_pattern(self.device_name, self._pattern.get())
        self.client.set_brightness_sync(self.device_name, self._sync.get())
        self.client.set_manual_brightness(self.device_name, int(self._manual.get()))
        mn, mx = self._range_slider.get()
        self.client.set_brightness_range(self.device_name, mn, mx)
        self.client.set_invert(self.device_name, self._invert.get())
        self.client.set_gamma(self.device_name, self._gamma.get())

        for zname, var in getattr(self, "_zone_counts", {}).items():
            self.client.set_led_count(self.device_name, zname, int(var.get()))

        self.client.reload_config()
        self.on_save()
        self.win.destroy()


# ---------------------------------------------------------------------------
# Colors Dialog
# ---------------------------------------------------------------------------

class ColorsDialog:
    """Dialog to pick which extracted wallpaper colors to use."""

    def __init__(self, colors: List[str], selected: List[int], on_save: Callable):
        self.colors = colors
        self.selected = set(selected)
        self.on_save = on_save

        self.win = tk.Toplevel()
        self.win.title("Iridia — Colors from Wallpaper")
        self.win.geometry("350x400")
        self.win.configure(bg="#1e1e1e")

        self._build()

    def _build(self):
        tk.Label(self.win, text="Select colors to use in patterns:",
                 bg="#1e1e1e", fg="white", font=("", 11, "bold")).pack(pady=10)

        self._vars = []
        for i, c in enumerate(self.colors):
            frame = tk.Frame(self.win, bg="#1e1e1e")
            frame.pack(anchor="w", fill="x", padx=20, pady=3)

            var = tk.BooleanVar(value=i in self.selected)
            self._vars.append(var)
            tk.Checkbutton(frame, variable=var, bg="#1e1e1e", selectcolor="#333").pack(side="left")

            # Color swatch
            canvas = tk.Canvas(frame, width=20, height=20, bg=f"#{c}", highlightthickness=1,
                               highlightbackground="#555")
            canvas.pack(side="left", padx=5)

            tk.Label(frame, text=f"#{c}", bg="#1e1e1e", fg="#ccc", font=("DejaVu Sans Mono", 10)).pack(side="left")

        frame = tk.Frame(self.win, bg="#1e1e1e")
        frame.pack(pady=15)
        tk.Button(frame, text="Auto-Select Best 4", command=self._auto_select,
                  bg="#444", fg="white").pack(side="left", padx=5)
        tk.Button(frame, text="Save", command=self._save,
                  bg="#00aa66", fg="white", width=10).pack(side="left", padx=5)
        tk.Button(frame, text="Cancel", command=self.win.destroy,
                  bg="#444", fg="white", width=10).pack(side="left", padx=5)

    def _auto_select(self):
        for i, var in enumerate(self._vars):
            var.set(i < min(4, len(self._vars)))

    def _save(self):
        selected = [i for i, var in enumerate(self._vars) if var.get()]
        self.on_save(selected)
        self.win.destroy()


# ---------------------------------------------------------------------------
# Palette Editor Dialog
# ---------------------------------------------------------------------------

class PaletteDialog:
    """Dialog to edit the 48-color palette."""

    def __init__(self, palette: Palette, on_save: Callable):
        self.palette = palette
        self.on_save = on_save
        self._entries = []

        self.win = tk.Toplevel()
        self.win.title("Iridia — 48-Color Palette Editor")
        self.win.geometry("420x600")
        self.win.configure(bg="#1e1e1e")

        self._build()

    def _build(self):
        # Header
        header = tk.Frame(self.win, bg="#1e1e1e")
        header.pack(fill="x", padx=15, pady=10)
        tk.Label(header, text="48-Color Palette", bg="#1e1e1e", fg="white",
                 font=("", 13, "bold")).pack(side="left")
        tk.Button(header, text="Reset All", command=self._reset_all,
                  bg="#aa3300", fg="white").pack(side="right")

        # Scrollable frame
        canvas = tk.Canvas(self.win, bg="#1e1e1e", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.win, orient="vertical", command=canvas.yview)
        self._scroll_frame = tk.Frame(canvas, bg="#1e1e1e")

        self._scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True, padx=(15, 0))
        scrollbar.pack(side="right", fill="y")

        # Rows
        for i, (hue, hex_c, name) in enumerate(self.palette.colors):
            self._add_row(i, hue, hex_c, name)

        # Save button
        tk.Button(self.win, text="Save Palette", command=self._save,
                  bg="#00aa66", fg="white", font=("", 11)).pack(pady=15)

    def _add_row(self, idx: int, hue: float, hex_c: str, name: str):
        frame = tk.Frame(self._scroll_frame, bg="#1e1e1e")
        frame.pack(fill="x", pady=1)

        # Index
        tk.Label(frame, text=f"{idx+1:2d}", bg="#1e1e1e", fg="#888", width=3).pack(side="left")

        # Name
        tk.Label(frame, text=name, bg="#1e1e1e", fg="#ccc", width=18).pack(side="left")

        # Color swatch (clickable)
        swatch = tk.Canvas(frame, width=24, height=20, bg=f"#{hex_c}",
                           highlightthickness=1, highlightbackground="#555")
        swatch.pack(side="left", padx=5)

        # Hex entry
        var = tk.StringVar(value=hex_c)
        self._entries.append((idx, var, swatch))
        entry = tk.Entry(frame, textvariable=var, width=7, bg="#2a2a2a", fg="white",
                         insertbackground="white", font=("DejaVu Sans Mono", 10))
        entry.pack(side="left", padx=5)
        entry.bind("<Return>", lambda e, i=idx, v=var, s=swatch: self._update_swatch(i, v, s))
        entry.bind("<FocusOut>", lambda e, i=idx, v=var, s=swatch: self._update_swatch(i, v, s))

        # Color picker button
        tk.Button(frame, text="🎨", command=lambda i=idx, v=var, s=swatch: self._pick_color(i, v, s),
                  bg="#333", fg="white", width=2).pack(side="left", padx=2)

        # Reset button
        tk.Button(frame, text="↺", command=lambda i=idx, v=var, s=swatch: self._reset_one(i, v, s),
                  bg="#333", fg="white", width=2).pack(side="left", padx=2)

    def _update_swatch(self, idx, var, swatch):
        hex_c = var.get().lower().strip("#")
        if len(hex_c) == 6:
            try:
                int(hex_c, 16)
                swatch.configure(bg=f"#{hex_c}")
            except ValueError:
                pass

    def _pick_color(self, idx, var, swatch):
        current = var.get()
        color = colorchooser.askcolor(color=f"#{current}", title="Pick Color")[1]
        if color:
            hex_c = color.lstrip("#").lower()
            var.set(hex_c)
            swatch.configure(bg=f"#{hex_c}")

    def _reset_one(self, idx, var, swatch):
        from iridia.palette import DEFAULT_PALETTE
        default = DEFAULT_PALETTE[idx]
        var.set(default[1])
        swatch.configure(bg=f"#{default[1]}")

    def _reset_all(self):
        if not messagebox.askyesno("Reset Palette", "Reset all 48 colors to factory defaults?"):
            return
        from iridia.palette import DEFAULT_PALETTE
        for i, (idx, var, swatch) in enumerate(self._entries):
            default = DEFAULT_PALETTE[idx]
            var.set(default[1])
            swatch.configure(bg=f"#{default[1]}")

    def _save(self):
        for idx, var, _ in self._entries:
            hex_c = var.get().lower().strip("#")
            if len(hex_c) == 6:
                try:
                    int(hex_c, 16)
                    self.palette.update(idx, hex_c)
                except ValueError:
                    pass
        self.on_save()
        self.win.destroy()


# ---------------------------------------------------------------------------
# Settings Dialog
# ---------------------------------------------------------------------------

class SettingsDialog:
    """Timing, logging, and general settings dialog."""

    def __init__(self, config: dict, on_save: Callable):
        self.config = config
        self.on_save = on_save

        self.win = tk.Toplevel()
        self.win.title("Iridia — Settings")
        self.win.geometry("380x480")
        self.win.configure(bg="#1e1e1e")
        self.win.resizable(False, False)

        self._build()

    def _build(self):
        pad = {"padx": 15, "pady": 5}

        # Timing
        tk.Label(self.win, text="Timing & Retries", bg="#1e1e1e", fg="white",
                 font=("", 12, "bold")).pack(anchor="w", pady=(15, 5), **pad)

        t = self.config.get("timing", {})
        self._timing_vars = {}
        for key, label, default in [
            ("openrgb_retry_interval_sec", "OpenRGB retry (sec)", 5.0),
            ("device_enumeration_interval_sec", "Device re-scan (sec)", 10.0),
            ("ddc_poll_interval_sec", "DDC poll (sec)", 5.0),
            ("wallpaper_debounce_ms", "Wallpaper debounce (ms)", 300),
            ("health_check_interval_sec", "Health check (sec)", 30.0),
            ("socket_timeout_sec", "Socket timeout (sec)", 2.0),
        ]:
            frame = tk.Frame(self.win, bg="#1e1e1e")
            frame.pack(anchor="w", fill="x", **pad)
            tk.Label(frame, text=label, bg="#1e1e1e", fg="#ccc", width=25).pack(side="left")
            var = tk.StringVar(value=str(t.get(key, default)))
            self._timing_vars[key] = var
            tk.Entry(frame, textvariable=var, width=8, bg="#2a2a2a", fg="white",
                     insertbackground="white").pack(side="left")

        # Logging
        tk.Label(self.win, text="Logging", bg="#1e1e1e", fg="white",
                 font=("", 12, "bold")).pack(anchor="w", pady=(15, 5), **pad)

        l = self.config.get("logging", {})
        self._log_enabled = tk.BooleanVar(value=l.get("enabled", False))
        tk.Checkbutton(self.win, text="Enable log file", variable=self._log_enabled,
                       bg="#1e1e1e", fg="white", selectcolor="#333").pack(anchor="w", **pad)

        frame = tk.Frame(self.win, bg="#1e1e1e")
        frame.pack(anchor="w", fill="x", **pad)
        tk.Label(frame, text="Max size (KB):", bg="#1e1e1e", fg="#ccc").pack(side="left")
        self._log_size = tk.StringVar(value=str(l.get("max_size_kb", 1024)))
        tk.Entry(frame, textvariable=self._log_size, width=6, bg="#2a2a2a", fg="white").pack(side="left", padx=10)

        frame = tk.Frame(self.win, bg="#1e1e1e")
        frame.pack(anchor="w", fill="x", **pad)
        tk.Label(frame, text="Level:", bg="#1e1e1e", fg="#ccc").pack(side="left")
        self._log_level = ttk.Combobox(frame, values=["debug", "info", "warning", "error"],
                                       state="readonly", width=10)
        self._log_level.set(l.get("level", "info"))
        self._log_level.pack(side="left", padx=10)

        # Buttons
        frame = tk.Frame(self.win, bg="#1e1e1e")
        frame.pack(pady=20)
        tk.Button(frame, text="Save", command=self._save, bg="#00aa66", fg="white",
                  width=10).pack(side="left", padx=5)
        tk.Button(frame, text="Cancel", command=self.win.destroy, bg="#444", fg="white",
                  width=10).pack(side="left", padx=5)

    def _save(self):
        new_config = dict(self.config)
        new_config["timing"] = {}
        for key, var in self._timing_vars.items():
            try:
                val = float(var.get())
                new_config["timing"][key] = val
            except ValueError:
                pass

        new_config["logging"] = {
            "enabled": self._log_enabled.get(),
            "max_size_kb": int(self._log_size.get() or 1024),
            "level": self._log_level.get(),
        }

        self.on_save(new_config)
        self.win.destroy()


# ---------------------------------------------------------------------------
# Service Dialog
# ---------------------------------------------------------------------------

class ServiceDialog:
    """Install/remove/start/stop systemd service."""

    def __init__(self):
        self.win = tk.Toplevel()
        self.win.title("Iridia — Service")
        self.win.geometry("300x200")
        self.win.configure(bg="#1e1e1e")
        self.win.resizable(False, False)

        self._build()
        self._update_status()

    def _build(self):
        tk.Label(self.win, text="Systemd Service", bg="#1e1e1e", fg="white",
                 font=("", 13, "bold")).pack(pady=15)

        self._status_label = tk.Label(self.win, text="Checking...", bg="#1e1e1e", fg="#888")
        self._status_label.pack(pady=5)

        frame = tk.Frame(self.win, bg="#1e1e1e")
        frame.pack(pady=15)

        self._btn_start = tk.Button(frame, text="Start", command=self._start, bg="#00aa66", fg="white", width=8)
        self._btn_start.pack(side="left", padx=3)
        self._btn_stop = tk.Button(frame, text="Stop", command=self._stop, bg="#aa3300", fg="white", width=8)
        self._btn_stop.pack(side="left", padx=3)
        self._btn_install = tk.Button(frame, text="Install", command=self._install, bg="#444", fg="white", width=8)
        self._btn_install.pack(side="left", padx=3)
        self._btn_remove = tk.Button(frame, text="Remove", command=self._remove, bg="#444", fg="white", width=8)
        self._btn_remove.pack(side="left", padx=3)

    def _run(self, cmd):
        import subprocess
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        except Exception:
            return None

    def _update_status(self):
        result = self._run(["systemctl", "--user", "is-active", "iridia-daemon.service"])
        status = result.stdout.strip() if result else "unknown"
        color = "#00aa66" if status == "active" else "#aa3300" if status == "inactive" else "#888"
        self._status_label.config(text=f"Status: {status}", fg=color)
        self.win.after(2000, self._update_status)

    def _start(self):
        self._run(["systemctl", "--user", "start", "iridia-daemon.service"])

    def _stop(self):
        self._run(["systemctl", "--user", "stop", "iridia-daemon.service"])

    def _install(self):
        import subprocess
        subprocess.run(["iridia", "service", "install"])
        messagebox.showinfo("Service", "Service installed and started.")

    def _remove(self):
        if messagebox.askyesno("Remove Service", "Stop and remove the systemd service?\nConfig files will be preserved."):
            import subprocess
            subprocess.run(["iridia", "service", "remove"])
            messagebox.showinfo("Service", "Service removed.")
