#!/usr/bin/env python3
"""Tkinter GUI for an SI5351 clock generator on a Raspberry Pi (I2C)."""
import argparse
import json
import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import si5351

CONFIG_PATH = Path.home() / ".config" / "freqgen_gui.json"
STEPS = {"1 Hz": 1, "10 Hz": 10, "100 Hz": 100, "1 kHz": 1e3, "10 kHz": 10e3,
         "100 kHz": 100e3, "1 MHz": 1e6, "10 MHz": 10e6}
DEFAULT_CH = [
    {"enabled": False, "freq": 10e6, "drive": 3, "pll": 0, "step": "1 kHz"},
    {"enabled": False, "freq": 1e6, "drive": 3, "pll": 1, "step": "1 kHz"},
    {"enabled": False, "freq": 100e3, "drive": 3, "pll": 1, "step": "1 kHz"},
]
FREQ_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([kKmMgG]?)(?:[hH][zZ])?\s*$")


def parse_freq(text):
    m = FREQ_RE.match(text)
    if not m:
        raise ValueError("Cannot parse frequency (examples: 10M, 7.074MHz, 455k, 1000)")
    return float(m.group(1)) * {"": 1, "k": 1e3, "m": 1e6, "g": 1e9}[m.group(2).lower()]


def fmt_freq(hz):
    return f"{hz:,.2f}".replace(",", " ") + " Hz"


def open_device(args):
    """Returns (Si5351, banner_text). Falls back to simulation if no hardware."""
    reason = "--sim given"
    if not args.sim:
        try:
            bus = si5351.I2CBus(args.bus, args.addr)
            return si5351.Si5351(bus, args.xtal), ""
        except ImportError:
            reason = "smbus2 not installed"
        except OSError as e:
            reason = f"no SI5351 on i2c-{args.bus} @0x{args.addr:02X} ({e})"
    return si5351.Si5351(si5351.SimBus(), args.xtal), f"SIMULATION - {reason}"


class ChannelPanel(ttk.LabelFrame):
    def __init__(self, master, app, ch, init):
        super().__init__(master, text=f" CLK{ch} ", padding=8)
        self.app, self.ch = app, ch
        self.en = tk.BooleanVar(value=init["enabled"])
        self.freq = tk.StringVar(value=f"{init['freq']:.2f}")
        self.drive = tk.StringVar(value=f"{si5351.DRIVE_MA[init['drive']]} mA")
        self.pll = tk.StringVar(value="AB"[init["pll"]])
        self.step = tk.StringVar(value=init["step"])
        self.actual = tk.StringVar(value="")

        ttk.Checkbutton(self, text="Output on", variable=self.en,
                        command=self.apply).grid(row=0, column=0, sticky="w")
        ttk.Button(self, text="−", width=3, command=lambda: self.nudge(-1)).grid(row=0, column=1)
        e = ttk.Entry(self, textvariable=self.freq, width=18, justify="right",
                      font=("TkFixedFont", 16))
        e.grid(row=0, column=2, padx=4)
        e.bind("<Return>", lambda _: self.apply())
        e.bind("<MouseWheel>", lambda ev: self.nudge(1 if ev.delta > 0 else -1))
        e.bind("<Button-4>", lambda _: self.nudge(1))     # X11 wheel
        e.bind("<Button-5>", lambda _: self.nudge(-1))
        ttk.Button(self, text="+", width=3, command=lambda: self.nudge(1)).grid(row=0, column=3)
        ttk.Button(self, text="Set", command=self.apply).grid(row=0, column=4, padx=(8, 0))

        opts = ttk.Frame(self)
        opts.grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))
        for text, var, vals in (("Step", self.step, list(STEPS)),
                                ("Drive", self.drive, [f"{d} mA" for d in si5351.DRIVE_MA]),
                                ("PLL", self.pll, ["A", "B"])):
            ttk.Label(opts, text=text).pack(side="left", padx=(0, 3))
            cb = ttk.Combobox(opts, textvariable=var, values=vals, state="readonly",
                              width=8 if text != "PLL" else 3)
            cb.pack(side="left", padx=(0, 12))
            if text != "Step":
                cb.bind("<<ComboboxSelected>>", lambda _: self.apply())
        ttk.Label(self, textvariable=self.actual, foreground="#666").grid(
            row=2, column=0, columnspan=5, sticky="w", pady=(4, 0))

    def current(self):
        return {"enabled": self.en.get(), "freq": parse_freq(self.freq.get()),
                "drive": int(self.drive.get().split()[0]) // 2 - 1,
                "pll": "AB".index(self.pll.get()), "step": self.step.get()}

    def apply(self):
        try:
            s = self.current()
            actual = self.app.dev.configure(self.ch, s["freq"], s["drive"], s["pll"], s["enabled"])
        except (ValueError, OSError) as e:
            self.en.set(False)
            self.actual.set("")
            self.app.error(f"CLK{self.ch}: {e}")
            return False
        err = actual - s["freq"]
        self.actual.set(f"Actual: {fmt_freq(actual)}   (error {err:+.3f} Hz)"
                        + ("" if s["enabled"] else "   [off]"))
        self.app.error("")
        return True

    def set_freq(self, hz):
        self.freq.set(f"{hz:.2f}")
        return self.apply()

    def nudge(self, direction):
        try:
            hz = parse_freq(self.freq.get()) + direction * STEPS[self.step.get()]
        except ValueError as e:
            self.app.error(str(e))
            return
        self.set_freq(min(max(hz, si5351.F_MIN), si5351.F_MAX))


class App(tk.Tk):
    def __init__(self, dev, banner):
        super().__init__()
        self.title("SI5351 Frequency Generator")
        self.dev = dev
        self.sweep_job = None
        cfg = self.load_config()
        ttk.Style(self).theme_use("clam")

        if banner:
            tk.Label(self, text=banner, bg="#b36b00", fg="white").pack(fill="x")

        # reference settings
        ref = ttk.LabelFrame(self, text=" Reference ", padding=8)
        ref.pack(fill="x", padx=8, pady=(8, 0))
        self.xtal = tk.StringVar(value=str(int(cfg.get("xtal", dev.xtal_nominal) / 1e6)) + " MHz")
        self.ppm = tk.StringVar(value=str(cfg.get("ppm", 0.0)))
        ttk.Label(ref, text="Crystal").pack(side="left")
        ttk.Combobox(ref, textvariable=self.xtal, values=["25 MHz", "27 MHz"], state="readonly",
                     width=7).pack(side="left", padx=(4, 16))
        ttk.Label(ref, text="Correction [ppm]").pack(side="left")
        pe = ttk.Entry(ref, textvariable=self.ppm, width=8, justify="right")
        pe.pack(side="left", padx=4)
        pe.bind("<Return>", lambda _: self.apply_reference())
        ttk.Button(ref, text="Apply", command=self.apply_reference).pack(side="left", padx=4)
        self.dev.set_timing(float(self.xtal.get().split()[0]) * 1e6, float(self.ppm.get()))

        self.panels = []
        for ch in range(3):
            p = ChannelPanel(self, self, ch, {**DEFAULT_CH[ch], **cfg.get("ch", [{}] * 3)[ch]})
            p.pack(fill="x", padx=8, pady=(8, 0))
            self.panels.append(p)

        self.build_sweep()

        self.msg = tk.StringVar()
        ttk.Label(self, textvariable=self.msg, foreground="#c00").pack(fill="x", padx=8, pady=(6, 0))
        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w",
                  padding=(6, 2)).pack(fill="x", side="bottom", pady=(6, 0))

        for p in self.panels:                    # restore saved state
            if p.en.get():
                p.apply()
        self.poll_status()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---- sweep -------------------------------------------------------
    def build_sweep(self):
        f = ttk.LabelFrame(self, text=" Sweep ", padding=8)
        f.pack(fill="x", padx=8, pady=(8, 0))
        self.sw_ch = tk.StringVar(value="CLK0")
        self.sw_start = tk.StringVar(value="1M")
        self.sw_stop = tk.StringVar(value="2M")
        self.sw_step = tk.StringVar(value="10k")
        self.sw_dwell = tk.StringVar(value="100")
        self.sw_loop = tk.BooleanVar(value=True)
        col = 0
        for text, var, w in (("Start", self.sw_start, 9), ("Stop", self.sw_stop, 9),
                             ("Step", self.sw_step, 8), ("Dwell [ms]", self.sw_dwell, 6)):
            ttk.Label(f, text=text).grid(row=0, column=col, sticky="w", padx=(0, 3))
            ttk.Entry(f, textvariable=var, width=w, justify="right").grid(
                row=1, column=col, padx=(0, 8))
            col += 1
        ttk.Label(f, text="Channel").grid(row=0, column=col, sticky="w")
        ttk.Combobox(f, textvariable=self.sw_ch, values=["CLK0", "CLK1", "CLK2"],
                     state="readonly", width=6).grid(row=1, column=col, padx=(0, 8))
        ttk.Checkbutton(f, text="Repeat", variable=self.sw_loop).grid(row=1, column=col + 1)
        self.sw_btn = ttk.Button(f, text="Start", command=self.toggle_sweep)
        self.sw_btn.grid(row=1, column=col + 2, padx=(8, 0))

    def toggle_sweep(self):
        if self.sweep_job is not None:
            self.stop_sweep()
            return
        try:
            self._sw = (parse_freq(self.sw_start.get()), parse_freq(self.sw_stop.get()),
                        parse_freq(self.sw_step.get()), max(int(self.sw_dwell.get()), 1))
            if self._sw[2] <= 0 or self._sw[0] > self._sw[1]:
                raise ValueError("Sweep needs start <= stop and step > 0")
        except ValueError as e:
            self.error(str(e))
            return
        panel = self.panels[int(self.sw_ch.get()[-1])]
        panel.en.set(True)
        self._sw_panel, self._sw_f = panel, self._sw[0]
        self.sw_btn.config(text="Stop")
        self.sweep_job = self.after(0, self.sweep_tick)

    def sweep_tick(self):
        start, stop, step, dwell = self._sw
        if not self._sw_panel.set_freq(self._sw_f):
            return self.stop_sweep()
        self._sw_f += step
        if self._sw_f > stop:
            if not self.sw_loop.get():
                return self.stop_sweep()
            self._sw_f = start
        self.sweep_job = self.after(dwell, self.sweep_tick)

    def stop_sweep(self):
        if self.sweep_job is not None:
            self.after_cancel(self.sweep_job)
        self.sweep_job = None
        self.sw_btn.config(text="Start")

    # ---- misc --------------------------------------------------------
    def apply_reference(self):
        try:
            self.dev.set_timing(float(self.xtal.get().split()[0]) * 1e6, float(self.ppm.get()))
        except ValueError:
            return self.error("Invalid ppm value")
        for p in self.panels:
            if p.en.get():
                p.apply()

    def error(self, text):
        self.msg.set(text)

    def poll_status(self):
        try:
            s = self.dev.status()
            parts = []
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
        try:
            return json.loads(CONFIG_PATH.read_text())
        except (OSError, ValueError):
            return {}

    def save_config(self):
        try:
            cfg = {"xtal": float(self.xtal.get().split()[0]) * 1e6, "ppm": float(self.ppm.get()),
                   "ch": [p.current() for p in self.panels]}
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps(cfg, indent=1))
        except (OSError, ValueError):
            pass

    def on_close(self):
        self.stop_sweep()
        self.save_config()
        self.dev.close()          # outputs off
        self.destroy()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bus", type=int, default=1, help="I2C bus number (default 1)")
    ap.add_argument("--addr", type=lambda s: int(s, 0), default=si5351.I2C_ADDR)
    ap.add_argument("--xtal", type=float, default=25e6, help="crystal Hz (default 25e6)")
    ap.add_argument("--sim", action="store_true", help="run without hardware")
    args = ap.parse_args()
    dev, banner = open_device(args)
    App(dev, banner).mainloop()


if __name__ == "__main__":
    main()
