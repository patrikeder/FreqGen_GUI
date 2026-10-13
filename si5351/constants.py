"""Register addresses, limits and tuning constants of the SI5351 driver."""
I2C_ADDR = 0x60
C_DEN = 1048575          # fixed denominator for fractional parameters
F_MIN = 3_500
F_MAX = 200_000_000
VCO_DEFAULT = 900_000_000
DRIVE_MA = (2, 4, 6, 8)

REG_STATUS = 0
REG_OE = 3
REG_CLK_CTRL = 16        # +ch
REG_PLL_BASE = (26, 34)  # PLLA, PLLB
REG_MS_BASE = 42         # +8*ch
REG_PLL_RESET = 177
REG_PHASE = 165          # +ch, 7 bit, units of Tvco/4
REG_XTAL_LOAD = 183
REG_DIS_STATE = 24       # 2 bits per channel: state of a disabled output
REG_SSC = 149            # 149..161 spread spectrum block (PLL A only)
REG_FANOUT = 187
PHASE_MAX_STEPS = 127
OFF_STATES = ("Low", "High", "Hi-Z")     # value = register code 0, 1, 2
TRIM_MAX_PPM = 200.0     # PLL fine tune range
SSC_MAX_PCT = {False: 2.5, True: 1.5}    # down / center spread limits [%]
SSC_MIN_PCT = 0.1
SSC_MOD_HZ = 31_500      # fixed spread modulation rate
T_WALK = 0.4             # seconds an output is detuned to "walk" its phase (see _walk_phases)
PHASE_STEP_WALK = 0.02   # seconds one phase sweep step is detuned (see walk.py)
