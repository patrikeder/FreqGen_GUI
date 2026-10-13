"""Reference settings: crystal frequency and ppm correction (Extras tab)."""
import tkinter as tk
from tkinter import ttk


class ReferenceFrame(ttk.LabelFrame):
    """Crystal selection (25 / 27 MHz) and the ppm correction of its measured error."""

    def __init__(self, master, app, cfg):
        """Create the reference frame and give the restored values to the driver, so they
        are in place before any channel is programmed.

        Args:
            master: parent widget (the Extras tab).
            app: owning App (device access, channel panels, 3-phase state, error line).
            cfg: saved config dict ('xtal' in Hz and 'ppm').
        """
        super().__init__(master, text=" Reference ", padding=4)
        self.app = app
        self.xtal = tk.StringVar(
            value=str(int(cfg.get("xtal", app.dev.xtal_nominal) / 1e6)) + " MHz")
        self.ppm = tk.StringVar(value=str(cfg.get("ppm", 0.0)))
        ttk.Label(self, text="Crystal").pack(side="left")
        ttk.Combobox(self, textvariable=self.xtal, values=["25 MHz", "27 MHz"], state="readonly",
                     width=7).pack(side="left", padx=(4, 16))
        ttk.Label(self, text="Correction [ppm]").pack(side="left")
        pe = ttk.Entry(self, textvariable=self.ppm, width=8, justify="right")
        pe.pack(side="left", padx=4)
        pe.bind("<Return>", lambda _: self.apply())
        ttk.Button(self, text="Apply", command=self.apply).pack(side="left", padx=4)
        app.dev.set_timing(self.xtal_hz(), float(self.ppm.get()))

    def xtal_hz(self):
        """Selected nominal crystal frequency in Hz."""
        return float(self.xtal.get().split()[0]) * 1e6

    def apply(self):
        """Apply crystal / ppm settings to the driver and reprogram every enabled
        channel so the new reference takes effect (3-phase mode is realigned, a running
        phase sweep blocks the change)."""
        app = self.app
        if app.phase_sweep.running:
            app.error("Stop the phase sweep before changing the reference")
            return
        try:
            app.dev.set_timing(self.xtal_hz(), float(self.ppm.get()))
        except ValueError:
            return app.error("Invalid ppm value")
        if app.three_phase.active:               # realign with the new reference
            app.three_phase.start()
            return
        for p in app.panels:
            if p.en.get():
                p.apply()

    def to_config(self):
        """Settings for the config file (crystal in Hz, ppm)."""
        return {"xtal": self.xtal_hz(), "ppm": float(self.ppm.get())}
