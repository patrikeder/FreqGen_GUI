"""Three-phase output mode (Extras tab)."""
import tkinter as tk
from tkinter import ttk

import si5351

from .common import fmt_freq, parse_freq


class ThreePhaseFrame(ttk.LabelFrame):
    """Starts CLK0 / CLK1 / CLK2 as a 0 / 120 / 240 degree set and locks their panels.

    `active` is True while the mode runs; other parts of the GUI check it so they
    don't change a single channel and break the alignment.
    """

    def __init__(self, master, app, cfg):
        """Create the 3-phase frame: frequency, sequence (direction), PLL, drive and the
        Start / Stop buttons, plus a line reporting the method and achieved phases.

        Args:
            master: parent widget (the Extras tab).
            app: owning App (device access, channel panels, sweep, error line).
            cfg: saved config dict; its 'tp' entry restores the last settings.
        """
        super().__init__(master, text=" 3-phase (CLK0 / CLK1 / CLK2 = 0° / 120° / 240°) ",
                         padding=4)
        self.app = app
        self.active = False
        saved = cfg.get("tp", {})
        self.freq = tk.StringVar(value=saved.get("freq", "100k"))
        self.sequence = tk.StringVar(value=saved.get("dir", "0-120-240"))
        self.pll = tk.StringVar(value=saved.get("pll", "A"))
        self.drive = tk.StringVar(value=saved.get("drive", "8 mA"))
        self.result = tk.StringVar()
        row = ttk.Frame(self)
        row.pack(fill="x")
        ttk.Label(row, text="Frequency").pack(side="left")
        e = ttk.Entry(row, textvariable=self.freq, width=12, justify="right")
        e.pack(side="left", padx=(4, 10))
        e.bind("<Return>", lambda _: self.start())
        for text, var, vals, w in (("Sequence", self.sequence, ["0-120-240", "0-240-120"], 10),
                                   ("PLL", self.pll, ["A", "B"], 3),
                                   ("Drive", self.drive,
                                    [f"{d} mA" for d in si5351.DRIVE_MA], 6)):
            ttk.Label(row, text=text).pack(side="left", padx=(0, 3))
            ttk.Combobox(row, textvariable=var, values=vals, state="readonly",
                         width=w).pack(side="left", padx=(0, 10))
        ttk.Button(row, text="Start", command=self.start).pack(side="left")
        ttk.Button(row, text="Stop", command=self.stop).pack(side="left", padx=4)
        ttk.Label(self, textvariable=self.result, foreground="#666").pack(
            anchor="w", pady=(4, 0))

    def start(self):
        """Start button: program the three outputs as a 3-phase set and lock their panels.

        Below ~9.5 MHz the driver needs about half a second to walk the phases; the
        window is unresponsive meanwhile. Shows the method and the achieved phases.
        """
        try:
            freq = parse_freq(self.freq.get())
            drive = int(self.drive.get().split()[0]) // 2 - 1
            pll = "AB".index(self.pll.get())
            self.app.sweep.stop()
            self.app.phase_sweep.stop()
            self.result.set("Aligning phases ...")
            self.update_idletasks()
            res = self.app.dev.three_phase(freq, self.sequence.get() == "0-240-120", drive, pll)
        except (ValueError, OSError) as e:
            self.result.set("")
            self.app.error(f"3-phase: {e}")
            return
        self.app.error("")
        self.active = True
        # The channel panels now only display; changing them would break the alignment.
        for p, deg in zip(self.app.panels, res["phases"]):
            p.en.set(True)
            p.freq.set(f"{freq:.2f}")
            p.pll.set(self.pll.get())
            p.phase.set(round(deg))
            p.phase_text.set(f"{deg:.1f}°")
            p.set_locked(True)
        self.show(res["method"], res["actual_hz"], res["phases"])

    def show(self, method, actual_hz, phases):
        """Update the result line and the 'Actual' lines of the locked channel panels."""
        self.result.set(f"{method}:  CLK0 {phases[0]:.1f}°   CLK1 {phases[1]:.1f}°   "
                        f"CLK2 {phases[2]:.1f}°   at {fmt_freq(actual_hz)}")
        for p, deg in zip(self.app.panels, phases):
            p.actual.set(f"3-phase {deg:.1f}°   Actual: {fmt_freq(actual_hz)}")

    def retune(self, pll):
        """The PLL fine tune of `pll` changed while running: move only the PLL (the
        channels and their phases stay as they are) and refresh the displayed frequency."""
        dev = self.app.dev
        if dev.three_phase_pll() == pll:
            phases = [float(p.phase.get()) for p in self.app.panels]
            self.show("3-phase", dev.retune_three_phase(), phases)

    def stop(self):
        """Stop button: switch the three outputs off and unlock their panels."""
        if not self.active:
            return
        self.app.dev.stop_three_phase()
        self.active = False
        for p in self.app.panels:
            p.en.set(False)
            p.actual.set("")
            p.set_locked(False)
        self.result.set("")

    def to_config(self):
        """Settings for the config file."""
        return {"freq": self.freq.get(), "dir": self.sequence.get(),
                "pll": self.pll.get(), "drive": self.drive.get()}
