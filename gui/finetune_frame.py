"""PLL fine tune in ppm (Extras tab)."""
import tkinter as tk
from tkinter import ttk

import si5351


class FineTuneFrame(ttk.LabelFrame):
    """One slider + entry per PLL; shifts every output running from that PLL.

    The slider covers +/- TRIM_MAX_PPM, the entry accepts exact values (0.01 ppm).
    """

    def __init__(self, master, app, cfg):
        """Create the fine-tune frame.

        Args:
            master: parent widget (the Extras tab).
            app: owning App (device access, channel panels, 3-phase state, error line).
            cfg: saved config dict; its 'trim' entry restores the last values.
        """
        super().__init__(master, text=" PLL fine tune (all outputs on that PLL) ", padding=4)
        self.app = app
        self.columnconfigure(1, weight=1)
        saved = cfg.get("trim", [0.0, 0.0])
        self.ppm = [tk.DoubleVar(value=saved[i]) for i in range(2)]
        self.text = [tk.StringVar(value=f"{saved[i]:+.2f}") for i in range(2)]
        self._job = [None, None]
        for pll in range(2):
            ttk.Label(self, text=f"PLL {'AB'[pll]}").grid(row=pll, column=0, sticky="w")
            ttk.Scale(self, from_=-si5351.TRIM_MAX_PPM, to=si5351.TRIM_MAX_PPM,
                      variable=self.ppm[pll],
                      command=lambda _, p=pll: self.on_change(p)).grid(
                row=pll, column=1, sticky="ew", padx=8)
            e = ttk.Entry(self, textvariable=self.text[pll], width=8, justify="right")
            e.grid(row=pll, column=2)
            e.bind("<Return>", lambda _, p=pll: self.set_from_text(p))
            ttk.Label(self, text="ppm").grid(row=pll, column=3, padx=(3, 8))
            ttk.Button(self, text="0", width=3,
                       command=lambda p=pll: self.set(p, 0.0)).grid(row=pll, column=4)

    def set(self, pll, ppm):
        """Move PLL `pll`'s slider to `ppm` and apply it."""
        self.ppm[pll].set(ppm)
        self.on_change(pll)

    def set_from_text(self, pll):
        """Return pressed in an entry: parse the ppm value and apply it."""
        try:
            self.set(pll, float(self.text[pll].get()))
        except ValueError:
            self.app.error("Fine tune: enter a number in ppm")

    def on_change(self, pll):
        """Slider moved: update the text now and apply once it settles (100 ms debounce,
        same idea as ChannelPanel.on_phase)."""
        self.text[pll].set(f"{self.ppm[pll].get():+.2f}")
        if self._job[pll] is not None:
            self.after_cancel(self._job[pll])
        self._job[pll] = self.after(100, lambda: self.apply(pll))

    def apply(self, pll):
        """Give the new fine tune to the driver and re-apply the enabled channels on that
        PLL, which reprograms the PLL fraction and updates their 'Actual' lines."""
        self._job[pll] = None
        if self.app.phase_sweep.running:      # the channels must not be reprogrammed now
            self.app.error("Stop the phase sweep before changing the fine tune")
            self.ppm[pll].set(self.app.dev.trim_ppm[pll])
            self.text[pll].set(f"{self.ppm[pll].get():+.2f}")
            return
        try:
            self.app.dev.set_trim(pll, round(self.ppm[pll].get(), 2))
        except ValueError as e:
            self.app.error(str(e))
            return
        # 3-phase running: only the PLL moves, the channels (and their phases) stay as is.
        if self.app.three_phase.active:
            self.app.three_phase.retune(pll)
            return
        for p in self.app.panels:
            if p.en.get() and not p.xtal.get() and p.pll.get() == "AB"[pll]:
                p.apply()

    def restore(self):
        """Push the saved values into the driver (before any channel is programmed)."""
        for pll in range(2):
            try:
                self.app.dev.set_trim(pll, self.ppm[pll].get())
            except ValueError:
                self.ppm[pll].set(0.0)

    def to_config(self):
        """Settings for the config file."""
        return [round(v.get(), 2) for v in self.ppm]
