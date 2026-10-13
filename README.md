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

## Layout
```
freqgen_gui.py            entry point (command line, open chip, start window)
gui/                      Tkinter GUI
  app.py                  main window: reference, Outputs / Extras tabs, status, config
  channel_panel.py        one output (Outputs tab)
  three_phase_frame.py    3-phase mode        } Extras tab
  sweep_frame.py          frequency sweep     }
  phase_sweep_frame.py    phase sweep         }
  spread_frame.py         spread spectrum     }
  finetune_frame.py       PLL fine tune       }
  reference_frame.py      crystal / ppm       }
  common.py               frequency parsing, defaults, config path
si5351/                   chip driver (usable without the GUI)
  device.py               Si5351 class: init, configure(), disable(), status()
  planning.py             divider / phase maths, register packing (no I2C)
  three_phase.py          0/120/240 deg mode (mixin)
  walk.py                 phase shifting by detuning (mixin, used by 3-phase and phase sweep)
  spread.py               spread spectrum (mixin + register maths)
  bus.py                  I2CBus (smbus2) and SimBus (simulator)
  constants.py            register map and limits
```

## Features
Two tabs: **Outputs** (the three channels) and **Extras** (3-phase, frequency sweep, phase sweep, spread spectrum, PLL fine tune, reference).

* 3 outputs, 3.5 kHz – 200 MHz, entry like `10M`, `7.074MHz`, `455k`; ± step buttons / mouse wheel
* Drive 2/4/6/8 mA, PLL A/B selection per output, crystal 25/27 MHz and ppm correction
* 3-phase mode: CLK0/1/2 at 0°/120°/240° (or reversed sequence) on one PLL, one click.
  Above ~9.5 MHz the phase registers do it (240° = 60° + invert); below that the driver
  "walks" the phases by briefly detuning CLK1/CLK2 (about 0.4 s, accuracy ~0.1° in theory)
* Phase slider per output (0–360°, relative to other outputs on the same PLL at the same frequency)
* Per output: invert (180°), crystal passthrough (25/27 MHz straight from the crystal), off-state (low / high / Hi-Z)
* PLL fine tune ±200 ppm per PLL (≈0.03 ppm steps, no PLL reset) for locking or slow FM
* Spread spectrum on PLL A: down 0.1–2.5 % or center ±0.1–1.5 %, ~31.5 kHz (formulas from AN619)
* Frequency sweep (start/stop/step/dwell, repeat)
* Phase sweep: phase of one output against a selectable reference output, in degrees
  (start/stop/step/dwell, repeat). Works up to 112.5 MHz by phase walking, ~0.1° per step
  in theory; each step is corrected for the error of the previous ones.
* PLL lock / crystal loss status; settings saved to `~/.config/freqgen_gui.json`

## Notes
* Up to 112.5 MHz all outputs share a 900 MHz VCO, so they can use the same PLL.
  Above 112.5 MHz the PLL VCO follows the output, so such a channel needs its own PLL.
* Output is 3.3 V square wave with ~50 Ω source impedance; don't load beyond the drive setting.
* 3-phase limits: the output can't go below 3.5 kHz, so slow motors need the chip as a 6x clock
  for an external counter. After the phases are set, don't change one output's frequency alone;
  use the 3-phase Start again (or the PLL fine tune, which keeps the phases).
