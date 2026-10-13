"""One output channel: the control panel shown on the Outputs tab."""
import tkinter as tk
from tkinter import ttk

import si5351

from .common import STEPS, fmt_freq, parse_freq


class ChannelPanel(ttk.LabelFrame):
    """Controls of one output: on/off, frequency entry with +/- stepping, step size,
    drive, PLL, invert, crystal passthrough, off-state, phase slider with presets and
    a line showing the achieved values.

    Every control change calls apply(), which reprograms the chip immediately.
    """

    def __init__(self, master, app, ch, init):
        """Build the widgets.

        Args:
            master: parent widget.
            app: owning App (gives access to the device and the error line).
            ch: channel number 0..2.
            init: dict with initial enabled/freq/drive/pll/step/phase/invert/off/xtal
                values (defaults merged with the saved config).
        """
        super().__init__(master, text=f" CLK{ch} ", padding=4)
        # Tk variables hold the widget state; apply() reads them back through current().
        self.app, self.ch = app, ch
        self.en = tk.BooleanVar(value=init["enabled"])
        self.freq = tk.StringVar(value=f"{init['freq']:.2f}")
        self.drive = tk.StringVar(value=f"{si5351.DRIVE_MA[init['drive']]} mA")
        self.pll = tk.StringVar(value="AB"[init["pll"]])
        self.step = tk.StringVar(value=init["step"])
        self.actual = tk.StringVar(value="")
        self.phase = tk.DoubleVar(value=init["phase"])
        self.phase_text = tk.StringVar()
        self.invert = tk.BooleanVar(value=init["invert"])
        self.off = tk.StringVar(value=si5351.OFF_STATES[init["off"]])
        self.xtal = tk.BooleanVar(value=init["xtal"])
        self._phase_job = None

        # Row 0: on/off checkbox, [-] frequency entry [+] and Set. Return in the entry and the
        # mouse wheel (<MouseWheel> on Windows/macOS, Button-4/5 on X11) also change the chip.
        ttk.Checkbutton(self, text="Output on", variable=self.en,
                        command=self.apply).grid(row=0, column=0, sticky="w")
        minus = ttk.Button(self, text="−", width=3, command=lambda: self.nudge(-1))
        minus.grid(row=0, column=1)
        e = ttk.Entry(self, textvariable=self.freq, width=18, justify="right",
                      font=("TkFixedFont", 14))
        e.grid(row=0, column=2, padx=4)
        e.bind("<Return>", lambda _: self.apply())
        e.bind("<MouseWheel>", lambda ev: self.nudge(1 if ev.delta > 0 else -1))
        e.bind("<Button-4>", lambda _: self.nudge(1))     # X11 wheel
        e.bind("<Button-5>", lambda _: self.nudge(-1))
        plus = ttk.Button(self, text="+", width=3, command=lambda: self.nudge(1))
        plus.grid(row=0, column=3)
        setbtn = ttk.Button(self, text="Set", command=self.apply)
        setbtn.grid(row=0, column=4, padx=(8, 0))
        self._freq_widgets = (minus, e, plus, setbtn)     # greyed out in crystal-out mode

        # Row 1: step size (only used by -/+/wheel), drive current and PLL selector; drive
        # and PLL reprogram the chip immediately when changed.
        opts = ttk.Frame(self)
        opts.grid(row=1, column=0, columnspan=5, sticky="w", pady=(3, 0))
        for text, var, vals in (("Step", self.step, list(STEPS)),
                                ("Drive", self.drive, [f"{d} mA" for d in si5351.DRIVE_MA]),
                                ("PLL", self.pll, ["A", "B"])):
            ttk.Label(opts, text=text).pack(side="left", padx=(0, 3))
            cb = ttk.Combobox(opts, textvariable=var, values=vals, state="readonly",
                              width=8 if text != "PLL" else 3)
            cb.pack(side="left", padx=(0, 12))
            if text != "Step":
                cb.bind("<<ComboboxSelected>>", lambda _: self.apply())
        # Same row: output options - invert (extra 180 deg), crystal passthrough (bypasses
        # PLL and Multisynth) and the level the pin takes while the output is off.
        ttk.Checkbutton(opts, text="Invert (180°)", variable=self.invert,
                        command=self.apply).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(opts, text="Crystal out", variable=self.xtal,
                        command=self.on_xtal).pack(side="left", padx=(0, 12))
        ttk.Label(opts, text="Off state").pack(side="left", padx=(0, 3))
        cb = ttk.Combobox(opts, textvariable=self.off, values=list(si5351.OFF_STATES),
                          state="readonly", width=5)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda _: self.apply())
        # Row 2: phase slider 0..360 deg with the live value / quantised result, plus presets.
        ph = ttk.Frame(self)
        ph.grid(row=2, column=0, columnspan=5, sticky="ew", pady=(3, 0))
        ttk.Label(ph, text="Phase").pack(side="left")
        ttk.Scale(ph, from_=0, to=360, variable=self.phase, command=self.on_phase).pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Label(ph, textvariable=self.phase_text, width=22, font=("TkFixedFont", 10)).pack(
            side="left")
        for deg in (0, 90, 120):
            ttk.Button(ph, text=f"{deg}°", width=4,
                       command=lambda d=deg: self.set_phase(d)).pack(side="left", padx=(4, 0))
        # Row 3: achieved frequency, error and warnings, filled in by apply().
        ttk.Label(self, textvariable=self.actual, foreground="#666").grid(
            row=3, column=0, columnspan=5, sticky="w", pady=(2, 0))
        self.phase_text.set(f"{self.phase.get():.0f}°")
        self.set_freq_widgets()

    def current(self):
        """Read the widgets into a dict (enabled, freq, drive, pll, step, phase, invert,
        off, xtal).

        Also the format stored in the config file. Raises ValueError if the
        frequency text can't be parsed.
        """
        return {"enabled": self.en.get(), "freq": parse_freq(self.freq.get()),
                "drive": int(self.drive.get().split()[0]) // 2 - 1,
                "pll": "AB".index(self.pll.get()), "step": self.step.get(),
                "phase": round(self.phase.get()), "invert": self.invert.get(),
                "off": si5351.OFF_STATES.index(self.off.get()), "xtal": self.xtal.get()}

    def set_freq_widgets(self):
        """Grey out the frequency controls while the output is the crystal passthrough."""
        state = "disabled" if self.xtal.get() else "!disabled"
        for w in self._freq_widgets:
            w.state([state])

    def set_locked(self, locked):
        """Grey out / restore every control of this panel (while 3-phase mode owns it)."""
        def walk(widget):
            for child in widget.winfo_children():
                try:
                    child.state(["disabled" if locked else "!disabled"])
                except (AttributeError, tk.TclError):     # plain tk widgets have no state()
                    pass
                walk(child)
        walk(self)
        if not locked:
            self.set_freq_widgets()

    def on_xtal(self):
        """Crystal-out checkbox: update the widget states and program the chip."""
        self.set_freq_widgets()
        self.apply()

    def set_phase(self, deg):
        """Preset-button handler: move the slider to `deg` and program it."""
        self.phase.set(deg)
        self.on_phase()

    def on_phase(self, _=None):
        """Slider moved: show the value now, program the chip once it settles."""
        self.phase_text.set(f"{round(self.phase.get())}°")
        # Debounce: dragging fires many events, so restart the timer; the chip is programmed
        # once, 150 ms after the slider stopped.
        if self._phase_job is not None:
            self.after_cancel(self._phase_job)
        self._phase_job = self.after(150, self.apply)

    def apply(self):
        """Program this channel from the current widget values.

        Shows the actual frequency / error / quantised phase below the controls.
        On failure (bad text, PLL conflict, I2C error) the output is switched off
        in the GUI, the error is shown in the message line and False is returned.

        Returns:
            True if the chip was programmed.
        """
        try:
            # Any pending slider timer is obsolete now - this call programs the current value.
            self._phase_job = None
            s = self.current()
            # Program the chip; raises ValueError (bad value, PLL conflict) or OSError (I2C).
            actual, deg, max_deg = self.app.dev.configure(
                self.ch, s["freq"], s["drive"], s["pll"], s["enabled"], s["phase"],
                s["invert"], s["off"], s["xtal"])
        # Show the channel as off, clear the result line and report the problem.
        except (ValueError, OSError) as e:
            self.en.set(False)
            self.actual.set("")
            self.app.error(f"CLK{self.ch}: {e}")
            return False
        # Crystal passthrough: nothing to quantise, just show the (ppm corrected) crystal.
        if s["xtal"]:
            self.actual.set(f"Crystal output: {fmt_freq(actual)}"
                            + ("" if s["enabled"] else "   [off]"))
            self.app.error("")
            return True
        # Success: display what the chip really produces (frequency, error, quantised phase),
        # warn if the phase was clamped, and mark the line when the output is off.
        err = actual - s["freq"]
        self.phase_text.set(f"{s['phase']}° -> {deg:.1f}°" if abs(deg - s["phase"]) >= 0.05
                            else f"{s['phase']}°")
        limit = f"   Phase max {max_deg:.0f}° at this frequency" if s["phase"] > max_deg + 0.5 else ""
        self.actual.set(f"Actual: {fmt_freq(actual)}   (error {err:+.3f} Hz)"
                        + limit + ("" if s["enabled"] else "   [off]"))
        self.app.error("")
        return True

    def set_freq(self, hz):
        """Set the frequency field to `hz` and program the chip (used by the sweep).

        Returns:
            True on success, see apply().
        """
        self.freq.set(f"{hz:.2f}")
        return self.apply()

    def nudge(self, direction):
        """Add direction * selected step to the frequency (+1 / -1, clamped to the
        chip range). Used by the +/- buttons and the mouse wheel."""
        try:
            hz = parse_freq(self.freq.get()) + direction * STEPS[self.step.get()]
        except ValueError as e:
            self.app.error(str(e))
            return
        self.set_freq(min(max(hz, si5351.F_MIN), si5351.F_MAX))
