# SI5351 Frequency Generator GUI

Tkinter GUI for an SI5351A breakout (Adafruit/generic, 25 MHz crystal) on a Raspberry Pi 5.

## Wiring
| SI5351 | Pi 5 |
|---|---|
| VIN/VCC | 3.3 V (pin 1) |
| GND | GND (pin 6) |
| SDA | GPIO2 (pin 3) |
| SCL | GPIO3 (pin 5) |

## Setup (on the Pi)
```bash
sudo raspi-config nonint do_i2c 0      # enable I2C
sudo apt install python3-tk i2c-tools
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
i2cdetect -y 1                         # should show 60
.venv/bin/python freqgen_gui.py
```
No hardware? `python freqgen_gui.py --sim` (also used automatically when no chip is found).

Options: `--bus 1 --addr 0x60 --xtal 25e6`.

## Features
* 3 outputs, 3.5 kHz – 200 MHz, entry like `10M`, `7.074MHz`, `455k`; ± step buttons / mouse wheel
* Drive 2/4/6/8 mA, PLL A/B selection per output, crystal 25/27 MHz and ppm correction
* Sweep (start/stop/step/dwell, repeat)
* PLL lock / crystal loss status; settings saved to `~/.config/freqgen_gui.json`

## Notes
* Up to 112.5 MHz all outputs share a 900 MHz VCO, so they can use the same PLL.
  Above 112.5 MHz the PLL VCO follows the output, so such a channel needs its own PLL.
* Output is 3.3 V square wave with ~50 Ω source impedance; don't load beyond the drive setting.
