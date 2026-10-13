"""Main window: Outputs tab, Extras tab, message and status lines."""
import json
import tkinter as tk
from tkinter import ttk

from .channel_panel import ChannelPanel
from .common import CONFIG_PATH, DEFAULT_CH
from .finetune_frame import FineTuneFrame
from .phase_sweep_frame import PhaseSweepFrame
from .reference_frame import ReferenceFrame
from .spread_frame import SpreadFrame
from .sweep_frame import SweepFrame
from .three_phase_frame import ThreePhaseFrame


class App(tk.Tk):
    """Main window with two tabs: Outputs (the three ChannelPanels) and Extras (3-phase,
    frequency and phase sweep, spread spectrum, PLL fine tune, reference). The message and
    status lines at the bottom are always visible."""

    def __init__(self, dev, banner):
        """Build the window, restore the saved config and re-apply channels that
        were on when the program was last closed.

        Args:
            dev: Si5351 instance (real or simulated).
            banner: text for the warning bar at the top, '' for none.
        """
        super().__init__()
        self.title("SI5351 Frequency Generator")
        self.dev = dev
        cfg = self.load_config()
        ttk.Style(self).theme_use("clam")

        # Orange warning bar when running without hardware.
        if banner:
            tk.Label(self, text=banner, bg="#b36b00", fg="white").pack(fill="x")

        # Bottom area first, so it keeps its place when the window is made small: red
        # error line above the sunken status bar.
        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w",
                  padding=(6, 2)).pack(fill="x", side="bottom")
        self.msg = tk.StringVar()
        ttk.Label(self, textvariable=self.msg, foreground="#c00").pack(
            fill="x", side="bottom", padx=8, pady=(4, 2))

        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        outputs = ttk.Frame(tabs)
        extras = ttk.Frame(tabs)
        tabs.add(outputs, text="Outputs")
        tabs.add(extras, text="Extras")

        # Outputs tab: one panel per output; saved values override DEFAULT_CH.
        self.panels = []
        saved = cfg.get("ch", [{}] * 3)
        for ch in range(3):
            p = ChannelPanel(outputs, self, ch, {**DEFAULT_CH[ch], **saved[ch]})
            p.pack(fill="x", pady=(4, 0))
            self.panels.append(p)

        # Extras tab. The frames reach each other through the App (three_phase.active
        # blocks sweeping, fine tune re-uses the 3-phase PLL, ...). The reference frame
        # hands crystal / ppm to the driver when it is created.
        self.three_phase = ThreePhaseFrame(extras, self, cfg)
        self.sweep = SweepFrame(extras, self)
        self.phase_sweep = PhaseSweepFrame(extras, self)
        self.spread = SpreadFrame(extras, self, cfg)
        self.finetune = FineTuneFrame(extras, self, cfg)
        self.reference = ReferenceFrame(extras, self, cfg)
        for frame in (self.three_phase, self.sweep, self.phase_sweep, self.spread,
                      self.finetune, self.reference):
            frame.pack(fill="x", pady=(4, 0))

        # Restore fine tune and spread settings first, so the channels come up with them.
        self.finetune.restore()
        self.spread.apply()
        for p in self.panels:                    # restore saved state
            if p.en.get():
                p.apply()
        self.poll_status()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def error(self, text):
        """Show `text` in the red message line ('' clears it)."""
        self.msg.set(text)

    def poll_status(self):
        """Once per second: read the chip status and show PLL A/B lock and crystal
        loss in the status bar (or 'simulated' / the I2C error)."""
        try:
            s = self.dev.status()
            parts = []
            # Real chip: PLL lock flags and crystal loss. Simulation has nothing to report.
            if self.dev.simulated:
                parts.append("simulated")
            else:
                parts.append("PLLA lock" if not s["lol_a"] else "PLLA UNLOCKED")
                parts.append("PLLB lock" if not s["lol_b"] else "PLLB UNLOCKED")
                parts.append("XTAL LOSS" if s["los"] else "XTAL ok")
            self.status.set("  |  ".join(parts))
        except OSError as e:
            self.status.set(f"I2C error: {e}")
        self.after(1000, self.poll_status)

    @staticmethod
    def load_config():
        """Read the saved settings from CONFIG_PATH; {} if missing or corrupt."""
        try:
            return json.loads(CONFIG_PATH.read_text())
        except (OSError, ValueError):
            return {}

    def save_config(self):
        """Write crystal, ppm and the settings of every part of the GUI to CONFIG_PATH
        as JSON. Errors are ignored (the settings are only a convenience)."""
        try:
            cfg = {**self.reference.to_config(),
                   "ch": [p.current() for p in self.panels],
                   "trim": self.finetune.to_config(), "tp": self.three_phase.to_config(),
                   "ssc": self.spread.to_config()}
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps(cfg, indent=1))
        except (OSError, ValueError):
            pass

    def on_close(self):
        """Window close handler: stop sweeps and 3-phase mode (so the panels are saved as
        off, not as locked), save settings, switch all outputs off, destroy the window."""
        self.sweep.stop()
        self.phase_sweep.stop()
        self.three_phase.stop()
        self.save_config()
        self.dev.close()          # outputs off
        self.destroy()
