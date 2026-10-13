"""Frequency sweep of one output (Extras tab)."""
import tkinter as tk
from tkinter import ttk

from .common import parse_freq


class SweepFrame(ttk.LabelFrame):
    """Steps one channel from a start to a stop frequency with a dwell time per step.

    Runs on the Tk timer ('after'), so the window stays responsive.
    """

    def __init__(self, master, app):
        """Create the sweep frame: start / stop / step / dwell [ms], channel,
        repeat checkbox and the Start/Stop button.

        Args:
            master: parent widget (the Extras tab).
            app: owning App (device access, channel panels, error line, 3-phase state).
        """
        super().__init__(master, text=" Frequency sweep ", padding=4)
        self.app = app
        self.job = None                       # pending 'after' id while a sweep runs
        self.channel = tk.StringVar(value="CLK0")
        self.start_hz = tk.StringVar(value="1M")
        self.stop_hz = tk.StringVar(value="2M")
        self.step_hz = tk.StringVar(value="10k")
        self.dwell_ms = tk.StringVar(value="100")
        self.repeat = tk.BooleanVar(value=True)
        # Label above entry for Start / Stop / Step / Dwell, then channel selector,
        # repeat checkbox and the Start/Stop button, all in one row.
        col = 0
        for text, var, w in (("Start", self.start_hz, 9), ("Stop", self.stop_hz, 9),
                             ("Step", self.step_hz, 8), ("Dwell [ms]", self.dwell_ms, 6)):
            ttk.Label(self, text=text).grid(row=0, column=col, sticky="w", padx=(0, 3))
            ttk.Entry(self, textvariable=var, width=w, justify="right").grid(
                row=1, column=col, padx=(0, 8))
            col += 1
        ttk.Label(self, text="Channel").grid(row=0, column=col, sticky="w")
        ttk.Combobox(self, textvariable=self.channel, values=["CLK0", "CLK1", "CLK2"],
                     state="readonly", width=6).grid(row=1, column=col, padx=(0, 8))
        ttk.Checkbutton(self, text="Repeat", variable=self.repeat).grid(row=1, column=col + 1)
        self.button = ttk.Button(self, text="Start", command=self.toggle)
        self.button.grid(row=1, column=col + 2, padx=(8, 0))

    def toggle(self):
        """Start/Stop button: validate the fields, switch the chosen channel on and
        start stepping, or stop a running sweep."""
        if self.job is not None:
            self.stop()
            return
        if self.app.three_phase.active or self.app.phase_sweep.running:
            self.app.error("Stop the 3-phase mode / phase sweep before sweeping")
            return
        try:
            # Parse all fields; a ValueError (bad text, start > stop, step <= 0) is shown
            # in the message line and the sweep isn't started.
            self._range = (parse_freq(self.start_hz.get()), parse_freq(self.stop_hz.get()),
                           parse_freq(self.step_hz.get()), max(int(self.dwell_ms.get()), 1))
            if self._range[2] <= 0 or self._range[0] > self._range[1]:
                raise ValueError("Sweep needs start <= stop and step > 0")
        except ValueError as e:
            self.app.error(str(e))
            return
        # The chosen channel must be on; tick() then steps it from start to stop.
        self._panel = self.app.panels[int(self.channel.get()[-1])]
        self._panel.en.set(True)
        self._freq = self._range[0]
        self.button.config(text="Stop")
        self.job = self.after(0, self.tick)

    def tick(self):
        """One sweep step: set the next frequency on the channel, then reschedule
        itself after the dwell time (tk 'after' timer, GUI stays responsive).
        Wraps to the start frequency when repeat is on, otherwise stops at the end."""
        start, stop, step, dwell = self._range
        if not self._panel.set_freq(self._freq):
            return self.stop()
        # Advance; past the end either wrap to the start (repeat) or stop.
        self._freq += step
        if self._freq > stop:
            if not self.repeat.get():
                return self.stop()
            self._freq = start
        self.job = self.after(dwell, self.tick)

    def stop(self):
        """Cancel the running sweep timer (if any) and reset the button label."""
        if self.job is not None:
            self.after_cancel(self.job)
        self.job = None
        self.button.config(text="Start")
