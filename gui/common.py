"""Shared GUI helpers: config path, step table, default channel settings, frequency
parsing and formatting."""
import re
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "freqgen_gui.json"
STEPS = {"1 Hz": 1, "10 Hz": 10, "100 Hz": 100, "1 kHz": 1e3, "10 kHz": 10e3,
         "100 kHz": 100e3, "1 MHz": 1e6, "10 MHz": 10e6}
FREQ_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([kKmMgG]?)(?:[hH][zZ])?\s*$")


def channel_default(freq, pll):
    """Default settings of one channel (also defines the keys stored in the config)."""
    return {"enabled": False, "freq": freq, "drive": 3, "pll": pll, "step": "1 kHz",
            "phase": 0, "invert": False, "off": 0, "xtal": False}


DEFAULT_CH = [channel_default(10e6, 0), channel_default(1e6, 1), channel_default(100e3, 1)]


def parse_freq(text):
    """Convert user text like '10M', '7.074MHz', '455k' or '1000' into Hz.

    A trailing m/M means MHz (not milli). Raises ValueError with a hint on bad input.
    """
    m = FREQ_RE.match(text)
    if not m:
        raise ValueError("Cannot parse frequency (examples: 10M, 7.074MHz, 455k, 1000)")
    return float(m.group(1)) * {"": 1, "k": 1e3, "m": 1e6, "g": 1e9}[m.group(2).lower()]


def fmt_freq(hz):
    """Format Hz for display with a space as thousands separator, e.g. '7 074 000.00 Hz'."""
    return f"{hz:,.2f}".replace(",", " ") + " Hz"
