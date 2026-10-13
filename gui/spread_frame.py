"""Spread spectrum control for PLL A (Extras tab)."""
import tkinter as tk
from tkinter import ttk


class SpreadFrame(ttk.LabelFrame):
    """Enable, down/center mode and amount in % of the PLL A spread spectrum."""

    def __init__(self, master, app, cfg):
        """Create the spread-spectrum frame.

        Args:
            master: parent widget (the Extras tab).
            app: owning App (device access, error line).
            cfg: saved config dict; its 'ssc' entry restores the last settings.
        """
        super().__init__(master, text=" Spread spectrum (PLL A, ~31.5 kHz) ", padding=4)
        self.app = app
        saved = cfg.get("ssc", {})
        self.enabled = tk.BooleanVar(value=saved.get("enabled", False))
        self.mode = tk.StringVar(value=saved.get("mode", "Down"))
        self.percent = tk.StringVar(value=str(saved.get("percent", 1.0)))
        ttk.Checkbutton(self, text="Enable", variable=self.enabled,
                        command=self.apply).pack(side="left")
        cb = ttk.Combobox(self, textvariable=self.mode, values=["Down", "Center"],
                          state="readonly", width=7)
        cb.pack(side="left", padx=8)
        cb.bind("<<ComboboxSelected>>", lambda _: self.apply())
        ttk.Label(self, text="Amount [%]").pack(side="left")
        e = ttk.Entry(self, textvariable=self.percent, width=6, justify="right")
        e.pack(side="left", padx=4)
        e.bind("<Return>", lambda _: self.apply())
        ttk.Button(self, text="Apply", command=self.apply).pack(side="left", padx=4)
        ttk.Label(self, text="down 0.1-2.5 %, center ±0.1-1.5 %", foreground="#666").pack(
            side="left", padx=8)

    def apply(self):
        """Program spread spectrum from the widgets (off when 'Enable' is cleared).

        The driver applies it to PLL A, so only outputs set to PLL A are spread.
        An invalid amount switches it off and shows the allowed range.
        """
        dev = self.app.dev
        try:
            pct = float(self.percent.get()) if self.enabled.get() else 0.0
            dev.set_spread(pct, self.mode.get() == "Center")
        except ValueError as e:
            self.enabled.set(False)
            dev.set_spread(0.0)
            self.app.error(f"Spread: {e}")
            return
        self.app.error("")

    def to_config(self):
        """Settings for the config file."""
        try:
            pct = float(self.percent.get())
        except ValueError:
            pct = 1.0
        return {"enabled": self.enabled.get(), "mode": self.mode.get(), "percent": pct}
