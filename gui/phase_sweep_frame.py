"""Phase sweep: one output's phase against a reference output (Extras tab)."""
import tkinter as tk
from tkinter import ttk

from .common import parse_freq


def wrap180(deg):
    """Wrap an angle into -180..180 (the shortest way round)."""
    return (deg + 180) % 360 - 180


class PhaseSweepFrame(ttk.LabelFrame):
    """Sweeps the phase of one channel against a selectable reference channel.

    Both run at the reference channel's frequency on its PLL. They are first started in
    phase (PLL reset), then the swept channel is shifted step by step by phase walking
    (see si5351/walk.py), so this works at any frequency up to 112.5 MHz. Every step is
    corrected for the error of the previous ones, so the sweep doesn't drift.
    """

    def __init__(self, master, app):
        """Create the phase sweep frame: channel, reference, start / stop / step [deg],
        dwell [ms], repeat, the Start/Stop button and a line with the current phase.

        Args:
            master: parent widget (the Extras tab).
            app: owning App (device access, channel panels, other modes, error line).
        """
        super().__init__(master, text=" Phase sweep (phase of Channel relative to Reference) ",
                         padding=4)
        self.app = app
        self.running = False
        self.job = None                       # pending 'after' id while a sweep runs
        self.channel = tk.StringVar(value="CLK1")
        self.reference = tk.StringVar(value="CLK0")
        self.start_deg = tk.StringVar(value="0")
        self.stop_deg = tk.StringVar(value="360")
        self.step_deg = tk.StringVar(value="5")
        self.dwell_ms = tk.StringVar(value="100")
        self.repeat = tk.BooleanVar(value=True)
        self.info = tk.StringVar()
        row = ttk.Frame(self)
        row.pack(fill="x")
        col = 0
        for text, var, vals in (("Channel", self.channel, ["CLK0", "CLK1", "CLK2"]),
                                ("Reference", self.reference, ["CLK0", "CLK1", "CLK2"])):
            ttk.Label(row, text=text).grid(row=0, column=col, sticky="w")
            ttk.Combobox(row, textvariable=var, values=vals, state="readonly",
                         width=6).grid(row=1, column=col, padx=(0, 8))
            col += 1
        for text, var, w in (("Start [°]", self.start_deg, 6), ("Stop [°]", self.stop_deg, 6),
                             ("Step [°]", self.step_deg, 6), ("Dwell [ms]", self.dwell_ms, 6)):
            ttk.Label(row, text=text).grid(row=0, column=col, sticky="w")
            ttk.Entry(row, textvariable=var, width=w, justify="right").grid(
                row=1, column=col, padx=(0, 8))
            col += 1
        ttk.Checkbutton(row, text="Repeat", variable=self.repeat).grid(row=1, column=col)
        self.button = ttk.Button(row, text="Start", command=self.toggle)
        self.button.grid(row=1, column=col + 1, padx=(8, 0))
        ttk.Label(self, textvariable=self.info, foreground="#666").pack(anchor="w", pady=(2, 0))

    def toggle(self):
        """Start/Stop button."""
        if self.running:
            self.stop()
        else:
            self.start()

    def start(self):
        """Validate the fields, start both channels in phase at the reference frequency,
        lock their panels and begin stepping."""
        app = self.app
        if app.three_phase.active or app.sweep.job is not None:
            app.error("Stop the 3-phase mode / frequency sweep first")
            return
        try:
            ch, ref = int(self.channel.get()[-1]), int(self.reference.get()[-1])
            if ch == ref:
                raise ValueError("Channel and Reference must be different outputs")
            self._range = (float(self.start_deg.get()), float(self.stop_deg.get()),
                           float(self.step_deg.get()), max(int(self.dwell_ms.get()), 1))
            if self._range[2] <= 0 or self._range[0] > self._range[1]:
                raise ValueError("Sweep needs start <= stop and step > 0")
            tgt_panel, ref_panel = app.panels[ch], app.panels[ref]
            if tgt_panel.xtal.get() or ref_panel.xtal.get():
                raise ValueError("Crystal-out channels can't be phase swept")
            self._freq = parse_freq(ref_panel.freq.get())
            self._pll = "AB".index(ref_panel.pll.get())
        except ValueError as e:
            app.error(str(e))
            return
        # Start both at the reference frequency on one PLL with no phase offset, then reset
        # the PLL: all dividers restart together, so the relative phase is exactly 0 deg.
        tgt_panel.freq.set(ref_panel.freq.get())
        tgt_panel.pll.set(ref_panel.pll.get())
        for p in (tgt_panel, ref_panel):
            p.en.set(True)
            p.phase.set(0)
        if not (ref_panel.apply() and tgt_panel.apply()):
            return
        app.dev.reset_pll(self._pll)
        self._tgt, self._ref = ch, ref
        self._panels = (tgt_panel, ref_panel)
        for p in self._panels:
            p.set_locked(True)
        self._pos = 0.0                       # measured phase of the channel vs the reference
        self._target = self._range[0]         # phase wanted by the current step
        self.running = True
        self.button.config(text="Stop")
        app.error("")
        self.job = self.after(0, self.tick)

    def tick(self):
        """One step: walk the channel from where it measured last time to the target phase
        (so errors don't add up), show the result, advance the target (wrapping to the
        start when repeat is on, otherwise stopping after the last step) and reschedule."""
        start, stop, step, dwell = self._range
        try:
            done = self.app.dev.walk_phase(self._tgt, self._freq, wrap180(self._target - self._pos),
                                           self._pll)
        except (ValueError, OSError) as e:
            self.app.error(f"Phase sweep: {e}")
            return self.stop()
        self._pos = (self._pos + done) % 360
        shown = round(self._pos, 2) % 360                 # avoid "360.00" for 359.999
        self.info.set(f"CLK{self._tgt} lags CLK{self._ref} by {shown:.2f}°   "
                      f"(wanted {self._target % 360:.1f}°)   at {self._freq:,.0f} Hz")
        self._target += step
        if self._target > stop + 1e-9:
            if not self.repeat.get():
                return self.stop()
            self._target = start
        self.job = self.after(dwell, self.tick)

    def stop(self):
        """End the sweep: leave both outputs running at the last phase, restore the clock
        control (integer mode) and unlock the panels, whose phase display shows the result."""
        if self.job is not None:
            self.after_cancel(self.job)
        self.job = None
        if not self.running:
            return
        self.running = False
        self.button.config(text="Start")
        self.app.dev.restore_ctrl([self._tgt])
        tgt_panel, _ = self._panels
        tgt_panel.phase.set(round(self._pos))
        tgt_panel.phase_text.set(f"walked {self._pos:.1f}°")
        for p in self._panels:
            p.set_locked(False)
