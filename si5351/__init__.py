"""SI5351A clock generator driver for Raspberry Pi.

Typical use:
    from si5351 import I2CBus, Si5351
    dev = Si5351(I2CBus(1))
    dev.configure(0, 10e6)

Modules: constants (registers, limits), planning (divider maths), bus (I2C / simulator),
device (Si5351 class), spread (spread spectrum), three_phase (0/120/240 deg mode),
walk (phase shifting by detuning, for 3-phase and the phase sweep).
"""
from .bus import I2CBus, SimBus
from .constants import *  # noqa: F401,F403  (register map and limits are part of the API)
from .device import Si5351
from .planning import Plan, pack_params, phase_limits, plan_frequency, pll_value
from .spread import spread_registers
