"""Windowed GUI application for Iridia."""

import json
import os
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

from iridia.client import Client
from iridia.config import Config
from iridia.palette import Palette, DEFAULT_PALETTE
from iridia.dialogs import (
    DualRangeSlider, DeviceDialog, ColorsDialog, PaletteDialog, SettingsDialog, ServiceDialog
)


class IridiaGUI:
    """Main windowed application for Iridia."""

    def __init__(self):
        self.client = Client()
        self.config = Config()
        self.palette = Palette()
        self._status = {}
        self._running = True
        self._poll_thread = None

        self.root = tk.Tk()
        self.root.title("Iridia")
        self.root.geometry("640x520")
        self.root.configure(bg="#1a1a1a")
        self.root.minsize(500, 400)

        # Dark theme styling
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("TNotebook", background="#1a1a1a", borderwidth=0)
        self.style.configure("TNotebook.Tab", background="#2a2a2a", foreground="#ccc",
                            padding=(15, 5), font=("", 10))
        self.style.map("TNotebook.Tab", background=[("selected", "#00aa66")],
                       foreground=[("selected", "white")])
        self.style.configure("TFrame", background="#1a1a1a")
        self.style.configure("TLabel", background="#1a1a1a", foreground="#ccc")
        self.style.configure("Header.TLabel", background="#1a1a1a", foreground="white",
                            font=("", 14, "bold"))
        self.style.configure("Subheader.TLabel", background="#1a1a1a", foreground="#aaa",
                            font=("", 10))

        self._build_ui()
        self._start_polling()

    def _build_ui(self):
        # Header
        header = tk.Frame(self.root, bg="#1a1a1a", height=60)
        header.pack(fill="x", padx=20, pady=(15, 5))
        header.pack_propagate(False)

        self._icon_canvas = tk.Canvas(header, width=32, height=32, bg="#1a1a1a",
                                      highlightthickness=0)
        self._icon_canvas.pack(side="left", padx=(0, 10))
        self._draw_icon("00aa66")

        self._title_label = tk.Label(header, text="Iridia", bg="#1a1a1a", fg="white",
                                     font=("", 18, "bold"))
        self._title_label.pack(side="left")

        self._status_label = tk.Label(header, text="Connecting...", bg="#1a1a1a", fg="#888",
                                      font=("", 9))
        self._status_label.pack(side="right")

        # Notebook (tabs)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=15, pady=10)

        # Status tab
        self._status_frame = tk.Frame(self.notebook, bg="#1a1a1a")
        self.notebook.add(self._status_frame, text="Status")
        self._build_status_tab()

        # Devices tab
        self._devices_frame = tk.Frame(self.notebook, bg="#1a1a1a")
        self.notebook.add(self._devices_frame, text="Devices")
        self._build_devices_tab()

        # Colors tab
        self._colors_frame = tk.Frame(self.notebook, bg="#1a1a1a")
        self.notebook.add(self._colors_frame, text="Colors")
        self._build_colors_tab()

        # Palette tab
        self._palette_frame = tk.Frame(self.notebook, bg="#1a1a1a")
        self.notebook.add(self._palette_frame, text="Palette")
        self._build_palette_tab()

        # Settings tab
        self._settings_frame = tk.Frame(self.notebook, bg="#1a1a1a")
        self.notebook.add(self._settings_frame, text="Settings")
        self._build_settings_tab()

        # Service tab
        self._service_frame = tk.Frame(self.notebook, bg="#1a1a1a")
        self.notebook.add(self._service_frame, text="Service")
        self._build_service_tab()

        # Bottom bar
        bottom = tk.Frame(self.root, bg="#1a1a1a", height=40)
        bottom.pack(fill="x", padx=15, pady=5)
        bottom.pack_propagate(False)

        tk.Button(bottom, text="Refresh", command=self._do_refresh,
                  bg="#2a2a2a", fg="white", activebackground="#333").pack(side="left", padx=5)
        tk.Button(bottom, text="Restart Daemon", command=self._do_restart,
                  bg="#2a2a2a", fg="white", activebackground="#333").pack(side="left", padx=5)
        tk.Button(bottom, text="Open Config Folder", command=self._open_config,
                  bg="#2a2a2a", fg="white", activebackground="#333").pack(side="left", padx=5)
        tk.Button(bottom, text="Open Log Folder", command=self._open_log,
                  bg="#2a2a2a", fg="white", activebackground="#333").pack(side="left", padx=5)
        tk.Button(bottom, text="Quit", command=self._quit,
                  bg="#aa3300", fg="white", activebackground="#882200").pack(side="right", padx=5)

    def _draw_icon(self, hex_color: str):
        self._icon_canvas.delete("all")
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        self._icon_canvas.create_oval(2, 2, 30, 30, fill=f"#{hex_color}", outline="")

    # -----------------------------------------------------------------------
    # Status Tab
    # -----------------------------------------------------------------------

    def _build_status_tab(self):
        self._status_widgets = {}

        tk.Label(self._status_frame, text="Current Status", bg="#1a1a1a", fg="white",
                 font=("", 14, "bold")).pack(anchor="w", pady=(10, 15), padx=10)

        fields = [
            ("wallpaper", "Wallpaper:", "N/A"),
            ("dominant", "Dominant Color:", "N/A"),
            ("brightness", "Monitor Brightness:", "N/A"),
            ("ddc", "DDC Available:", "N/A"),
            ("openrgb", "OpenRGB Connected:", "N/A"),
            ("mode", "Mode:", "N/A"),
        ]

        for key, label, default in fields:
            frame = tk.Frame(self._status_frame, bg="#1a1a1a")
            frame.pack(anchor="w", fill="x", padx=20, pady=4)
            tk.Label(frame, text=label, bg="#1a1a1a", fg="#888", width=20,
                     font=("", 10)).pack(side="left")
            lbl = tk.Label(frame, text=default, bg="#1a1a1a", fg="white", font=("DejaVu Sans Mono", 10))
            lbl.pack(side="left")
            self._status_widgets[key] = lbl

        # Color swatches
        self._swatch_frame = tk.Frame(self._status_frame, bg="#1a1a1a")
        self._swatch_frame.pack(anchor="w", fill="x", padx=20, pady=15)
        tk.Label(self._swatch_frame, text="Extracted Colors:", bg="#1a1a1a",
                 fg="#888", font=("", 10)).pack(anchor="w", pady=(0, 5))
        self._swatches = []

    # -----------------------------------------------------------------------
    # Devices Tab
    # -----------------------------------------------------------------------

    def _build_devices_tab(self):
        self._devices_container = tk.Frame(self._devices_frame, bg="#1a1a1a")
        self._devices_container.pack(fill="both", expand=True, padx=10, pady=10)
        tk.Label(self._devices_container, text="No devices detected.", bg="#1a1a1a",
                 fg="#666", font=("", 11)).pack(pady=20)

    def _refresh_devices_tab(self):
        for w in self._devices_container.winfo_children():
            w.destroy()

        devices = self._status.get("device_configs", {})
        if not devices:
            tk.Label(self._devices_container, text="No devices configured.", bg="#1a1a1a",
                     fg="#666", font=("", 11)).pack(pady=20)
            return

        for name, cfg in devices.items():
            frame = tk.Frame(self._devices_container, bg="#222", padx=10, pady=10)
            frame.pack(fill="x", pady=5)

            enabled = cfg.get("enabled", True)
            status_color = "#00aa66" if enabled else "#aa3300"
            tk.Label(frame, text="●", bg="#222", fg=status_color, font=("", 14)).pack(side="left")
            tk.Label(frame, text=name, bg="#222", fg="white", font=("", 11, "bold")).pack(side="left", padx=5)

            info = f"{cfg.get('mode','palette')} | {cfg.get('pattern','solid')} | LEDs: {cfg.get('zones',{})}"
            tk.Label(frame, text=info, bg="#222", fg="#888", font=("", 9)).pack(side="left", padx=10)

            tk.Button(frame, text="Settings...", command=lambda n=name: self._open_device_dialog(n),
                      bg="#333", fg="white").pack(side="right", padx=5)

    # -----------------------------------------------------------------------
    # Colors Tab
    # -----------------------------------------------------------------------

    def _build_colors_tab(self):
        self._colors_container = tk.Frame(self._colors_frame, bg="#1a1a1a")
        self._colors_container.pack(fill="both", expand=True, padx=10, pady=10)
        tk.Label(self._colors_container, text="Change wallpaper to see colors.", bg="#1a1a1a",
                 fg="#666", font=("", 11)).pack(pady=20)

    def _refresh_colors_tab(self):
        for w in self._colors_container.winfo_children():
            w.destroy()

        colors = self._status.get("extracted_colors", [])
        if not colors:
            tk.Label(self._colors_container, text="No colors extracted.", bg="#1a1a1a",
                     fg="#666").pack(pady=20)
            return

        tk.Label(self._colors_container, text="Select colors to use in patterns:",
                 bg="#1a1a1a", fg="white", font=("", 12, "bold")).pack(anchor="w", pady=10)

        self._color_vars = []
        devices = self._status.get("device_configs", {})
        selected = set()
        for cfg in devices.values():
            selected.update(cfg.get("selected_colors", [0]))

        for i, c in enumerate(colors):
            frame = tk.Frame(self._colors_container, bg="#1a1a1a")
            frame.pack(anchor="w", fill="x", pady=3)

            var = tk.BooleanVar(value=i in selected)
            self._color_vars.append(var)
            tk.Checkbutton(frame, variable=var, bg="#1a1a1a", selectcolor="#333",
                           activebackground="#1a1a1a").pack(side="left")

            canvas = tk.Canvas(frame, width=24, height=24, bg=f"#{c}",
                               highlightthickness=1, highlightbackground="#555")
            canvas.pack(side="left", padx=5)
            tk.Label(frame, text=f"#{c}", bg="#1a1a1a", fg="#ccc",
                     font=("DejaVu Sans Mono", 10)).pack(side="left", padx=5)

        tk.Button(self._colors_container, text="Save Selection", command=self._save_color_selection,
                  bg="#00aa66", fg="white").pack(anchor="w", pady=15)

    def _save_color_selection(self):
        indices = [i for i, var in enumerate(self._color_vars) if var.get()]
        for name in self._status.get("device_configs", {}).keys():
            self.client.set_selected_colors(name, indices)
        self.client.reload_config()

    # -----------------------------------------------------------------------
    # Palette Tab
    # -----------------------------------------------------------------------

    def _build_palette_tab(self):
        container = tk.Frame(self._palette_frame, bg="#1a1a1a")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Label(container, text="48-Color Palette", bg="#1a1a1a", fg="white",
                 font=("", 14, "bold")).pack(anchor="w", pady=(0, 10))

        tk.Button(container, text="Open Palette Editor...", command=self._open_palette_dialog,
                  bg="#00aa66", fg="white", font=("", 11)).pack(anchor="w", pady=5)

        tk.Label(container, text="Quick Preview:", bg="#1a1a1a", fg="#888").pack(anchor="w", pady=(15, 5))

        # Show first 12 colors as a grid
        preview = tk.Frame(container, bg="#1a1a1a")
        preview.pack(fill="x")
        for i, (hue, hex_c, name) in enumerate(self.palette.colors[:12]):
            canvas = tk.Canvas(preview, width=40, height=40, bg=f"#{hex_c}",
                               highlightthickness=1, highlightbackground="#555")
            canvas.pack(side="left", padx=2, pady=2)

    # -----------------------------------------------------------------------
    # Settings Tab
    # -----------------------------------------------------------------------

    def _build_settings_tab(self):
        container = tk.Frame(self._settings_frame, bg="#1a1a1a")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Label(container, text="Settings", bg="#1a1a1a", fg="white",
                 font=("", 14, "bold")).pack(anchor="w", pady=(0, 10))

        tk.Button(container, text="Open Full Settings Dialog...", command=self._open_settings_dialog,
                  bg="#2a2a2a", fg="white", font=("", 11)).pack(anchor="w", pady=5)

        # Quick toggles
        frame = tk.Frame(container, bg="#1a1a1a")
        frame.pack(anchor="w", fill="x", pady=10)

        self._log_var = tk.BooleanVar(value=self.config.get("logging.enabled", False))
        tk.Checkbutton(frame, text="Enable Log File", variable=self._log_var,
                       bg="#1a1a1a", fg="white", selectcolor="#333",
                       command=self._toggle_log).pack(anchor="w")

        log_path = os.path.expanduser(self.config.get("logging.file_path", "~/.local/share/iridia/iridia.log"))
        tk.Label(container, text=f"Log: {log_path}", bg="#1a1a1a", fg="#888",
                 font=("", 9)).pack(anchor="w")

    def _toggle_log(self):
        self.config.set("logging.enabled", self._log_var.get())
        self.client.reload_config()

    # -----------------------------------------------------------------------
    # Service Tab
    # -----------------------------------------------------------------------

    def _build_service_tab(self):
        container = tk.Frame(self._service_frame, bg="#1a1a1a")
        container.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Label(container, text="Systemd Service", bg="#1a1a1a", fg="white",
                 font=("", 14, "bold")).pack(anchor="w", pady=(0, 10))

        self._svc_status = tk.Label(container, text="Checking...", bg="#1a1a1a",
                                    fg="#888", font=("", 11))
        self._svc_status.pack(anchor="w", pady=5)

        btn_frame = tk.Frame(container, bg="#1a1a1a")
        btn_frame.pack(anchor="w", pady=10)

        tk.Button(btn_frame, text="Start", command=self._svc_start,
                  bg="#00aa66", fg="white", width=10).pack(side="left", padx=3)
        tk.Button(btn_frame, text="Stop", command=self._svc_stop,
                  bg="#aa3300", fg="white", width=10).pack(side="left", padx=3)
        tk.Button(btn_frame, text="Install", command=self._svc_install,
                  bg="#2a2a2a", fg="white", width=10).pack(side="left", padx=3)
        tk.Button(btn_frame, text="Remove", command=self._svc_remove,
                  bg="#2a2a2a", fg="white", width=10).pack(side="left", padx=3)

        tk.Label(container, text="Config is preserved when removing the service.",
                 bg="#1a1a1a", fg="#666", font=("", 9)).pack(anchor="w", pady=10)

    def _update_service_tab(self):
        try:
            result = subprocess.run(["systemctl", "--user", "is-active", "iridia-daemon.service"],
                                    capture_output=True, text=True, timeout=3)
            status = result.stdout.strip()
            color = "#00aa66" if status == "active" else "#aa3300"
            self._svc_status.config(text=f"Service: {status}", fg=color)
        except Exception:
            self._svc_status.config(text="Service: unknown", fg="#888")

    def _svc_start(self):
        subprocess.run(["systemctl", "--user", "start", "iridia-daemon.service"], capture_output=True)
        self._update_service_tab()

    def _svc_stop(self):
        subprocess.run(["systemctl", "--user", "stop", "iridia-daemon.service"], capture_output=True)
        self._update_service_tab()

    def _svc_install(self):
        subprocess.run(["iridia", "service", "install"], capture_output=True)
        messagebox.showinfo("Service", "Service installed and started.")
        self._update_service_tab()

    def _svc_remove(self):
        if messagebox.askyesno("Remove Service", "Stop and remove the systemd service?\nConfig files will be preserved."):
            subprocess.run(["iridia", "service", "remove"], capture_output=True)
            messagebox.showinfo("Service", "Service removed.")
            self._update_service_tab()

    # -----------------------------------------------------------------------
    # Polling
    # -----------------------------------------------------------------------

    def _start_polling(self):
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

    def _poll_loop(self):
        while self._running:
            try:
                resp = self.client.status()
                if resp.get("ok"):
                    self._status = resp
                    self.root.after(0, self._update_ui)
                else:
                    self._status = {"_error": "daemon not running"}
                    self.root.after(0, self._update_ui)
            except Exception:
                self._status = {"_error": "connection failed"}
                self.root.after(0, self._update_ui)
            time.sleep(2)

    def _update_ui(self):
        if "_error" in self._status:
            self._status_label.config(text=self._status["_error"], fg="#aa3300")
            self._title_label.config(text="Iridia — Disconnected")
            return

        # Header
        colors = self._status.get("extracted_colors", [])
        wallpaper = self._status.get("wallpaper", "N/A")
        brightness = self._status.get("brightness", "?")
        dominant = colors[0] if colors else "00aa66"

        self._draw_icon(dominant)
        self._title_label.config(text="Iridia")
        self._status_label.config(text=f"#{dominant} | {brightness}% brightness", fg="#888")

        # Status tab
        wp_name = os.path.basename(wallpaper) if wallpaper != "N/A" else "N/A"
        self._status_widgets["wallpaper"].config(text=wp_name)
        self._status_widgets["dominant"].config(text=f"#{dominant}")
        self._status_widgets["brightness"].config(text=f"{brightness}%")
        self._status_widgets["ddc"].config(text="Yes" if self._status.get("ddc_available") else "No")
        self._status_widgets["openrgb"].config(text="Yes" if self._status.get("openrgb_connected") else "No")
        self._status_widgets["mode"].config(text=f"{self._status.get('mode','palette')} / {self._status.get('palette_mode','exact')}")

        # Color swatches
        for w in self._swatch_frame.winfo_children()[1:]:
            w.destroy()
        for c in colors[:8]:
            canvas = tk.Canvas(self._swatch_frame, width=32, height=32, bg=f"#{c}",
                               highlightthickness=1, highlightbackground="#555")
            canvas.pack(side="left", padx=2)

        # Refresh other tabs
        self._refresh_devices_tab()
        self._refresh_colors_tab()
        self._update_service_tab()

    # -----------------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------------

    def _open_device_dialog(self, name: str):
        cfg = self._status.get("device_configs", {}).get(name, {})
        if cfg:
            DeviceDialog(name, cfg, self.client, lambda: self.client.reload_config())

    def _open_palette_dialog(self):
        PaletteDialog(self.palette, lambda: self.client.reload_config())

    def _open_settings_dialog(self):
        SettingsDialog(self.config.raw, self._on_settings_save)

    def _on_settings_save(self, new_config: dict):
        path = os.path.expanduser("~/.config/iridia/config.json")
        with open(path, "w") as f:
            json.dump(new_config, f, indent=2)
        self.client.reload_config()

    def _do_refresh(self):
        self.client.refresh()

    def _do_restart(self):
        self.client.restart()

    def _open_config(self):
        path = os.path.expanduser("~/.config/iridia")
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _open_log(self):
        path = os.path.expanduser("~/.local/share/iridia")
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _quit(self):
        self._running = False
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    app = IridiaGUI()
    app.run()


if __name__ == "__main__":
    main()
