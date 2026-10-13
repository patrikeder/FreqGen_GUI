#!/usr/bin/env python3
"""Tkinter GUI for an SI5351 clock generator on a Raspberry Pi (I2C).

Entry point: parses the command line, opens the chip (or the simulator) and starts
the window from the `gui` package; the chip driver is the `si5351` package.
"""
import argparse

import si5351
from gui.app import App


def open_device(args):
    """Create the Si5351 object for the command line options.

    Tries real I2C first (unless --sim). If smbus2 is missing or no chip answers,
    falls back to SimBus so the GUI still starts for development.

    Returns:
        (Si5351, banner_text); banner_text is '' for real hardware, otherwise the
        reason for the simulation, shown as an orange bar in the window.
    """
    # Use the real chip unless simulation was requested; `reason` is shown in the banner
    # if we end up in simulation.
    reason = "--sim given"
    if not args.sim:
        try:
            # Raises ImportError (no smbus2) or OSError (no chip) -> handled below.
            bus = si5351.I2CBus(args.bus, args.addr)
            return si5351.Si5351(bus, args.xtal), ""
        except ImportError:
            reason = "smbus2 not installed"
        except OSError as e:
            reason = f"no SI5351 on i2c-{args.bus} @0x{args.addr:02X} ({e})"
    return si5351.Si5351(si5351.SimBus(), args.xtal), f"SIMULATION - {reason}"


def main():
    """Parse the command line (--bus, --addr, --xtal, --sim), open the device and
    run the Tk main loop."""
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
