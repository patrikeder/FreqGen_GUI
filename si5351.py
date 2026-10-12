"""Minimal SI5351A driver (3 outputs, 25/27 MHz crystal) for Raspberry Pi.

Strategy (same as most hobby drivers, see Skyworks AN619):
  * f <= 112.5 MHz : PLL fixed at 900 MHz, fractional Multisynth, R divider
                     for outputs below 500 kHz.
  * f  > 112.5 MHz : integer Multisynth divide-by-6 (<=150 MHz) or divide-by-4
                     (<=200 MHz); the PLL VCO is then 6*f / 4*f, so that PLL
                     can't be shared with a channel needing another VCO.
"""
from dataclasses import dataclass
from fractions import Fraction
import time

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
REG_XTAL_LOAD = 183


@dataclass(frozen=True)
class Plan:
    pll: tuple           # (a, b, c) PLL feedback multiplier
    ms: tuple            # (a, b, c) Multisynth divider
    r_exp: int           # output R divider = 2**r_exp
    divby4: bool
    actual_hz: float


def plan_frequency(freq_hz, xtal_hz):
    """Compute divider settings for freq_hz. Raises ValueError if impossible."""
    if not F_MIN <= freq_hz <= F_MAX:
        raise ValueError(f"Frequency must be {F_MIN / 1e3:g} kHz .. {F_MAX / 1e6:g} MHz")
    f = Fraction(freq_hz)
    xtal = Fraction(xtal_hz)
    r_exp = 0
    divby4 = False
    if f > Fraction(225, 2) * 10**6:                  # > 112.5 MHz: integer divider
        div = 4 if f > 150 * 10**6 else 6
        divby4 = div == 4
        ms = (div, 0, C_DEN)
        vco = f * div
    else:
        while f * 2**r_exp < 500_000 and r_exp < 7:
            r_exp += 1
        ratio = Fraction(VCO_DEFAULT) / (f * 2**r_exp)
        a = int(ratio)
        b = round((ratio - a) * C_DEN)
        if b == C_DEN:
            a, b = a + 1, 0
        ms = (a, b, C_DEN)
        vco = Fraction(VCO_DEFAULT)
    mult = vco / xtal
    pa = int(mult)
    pb = round((mult - pa) * C_DEN)
    if pb == C_DEN:
        pa, pb = pa + 1, 0
    if not (15 <= pa <= 90) or (pa == 90 and pb):
        raise ValueError("PLL multiplier out of range - check crystal frequency")
    vco_act = xtal * (pa + Fraction(pb, C_DEN))
    ms_val = ms[0] + Fraction(ms[1], ms[2])
    actual = float(vco_act / ms_val / 2**r_exp)
    return Plan((pa, pb, C_DEN), ms, r_exp, divby4, actual)


def pack_params(a, b, c, r_exp=0, divby4=False):
    """8 register bytes for a PLL or Multisynth parameter block."""
    x = (128 * b) // c
    p1 = 128 * a + x - 512
    p2 = 128 * b - c * x
    p3 = c
    if divby4:
        p1 = p2 = 0
        p3 = 1
    return [
        (p3 >> 8) & 0xFF,
        p3 & 0xFF,
        (r_exp << 4) | (0x0C if divby4 else 0) | ((p1 >> 16) & 0x03),
        (p1 >> 8) & 0xFF,
        p1 & 0xFF,
        (((p3 >> 16) & 0x0F) << 4) | ((p2 >> 16) & 0x0F),
        (p2 >> 8) & 0xFF,
        p2 & 0xFF,
    ]


class I2CBus:
    def __init__(self, busnum=1, addr=I2C_ADDR):
        from smbus2 import SMBus          # raises ImportError if missing
        self.bus = SMBus(busnum)
        self.addr = addr
        self.bus.read_byte_data(addr, REG_STATUS)   # raises OSError if no chip

    def write(self, reg, data):
        self.bus.write_i2c_block_data(self.addr, reg, list(data))

    def read(self, reg):
        return self.bus.read_byte_data(self.addr, reg)


class SimBus:
    """Register file stand-in so the GUI can run without hardware."""
    simulated = True

    def __init__(self):
        self.regs = [0] * 256

    def write(self, reg, data):
        for i, v in enumerate(data):
            self.regs[reg + i] = v

    def read(self, reg):
        return self.regs[reg]


class Si5351:
    NUM_CH = 3

    def __init__(self, bus, xtal_hz=25_000_000, ppm=0.0, load_pf=10):
        self.bus = bus
        self.xtal_nominal = xtal_hz
        self.ppm = ppm
        self._pll_cache = [None, None]
        self._active = {}                  # ch -> (pll_index, pll_params)
        self._oe_off = 0xFF
        self._wait_ready()
        bus.write(REG_OE, [0xFF])
        bus.write(REG_CLK_CTRL, [0x80] * 8)                    # power down all
        bus.write(REG_XTAL_LOAD, [{6: 0x52, 8: 0x92, 10: 0xD2}[load_pf]])
        # (bits 5:0 of reg 183 must be written as 010010 per datasheet)

    @property
    def simulated(self):
        return getattr(self.bus, "simulated", False)

    @property
    def xtal_hz(self):
        return self.xtal_nominal * (1 + self.ppm * 1e-6)

    def _wait_ready(self):
        for _ in range(50):
            if not self.bus.read(REG_STATUS) & 0x80:   # SYS_INIT
                return
            time.sleep(0.01)

    def set_timing(self, xtal_hz, ppm):
        """Change reference; caller must re-apply active channels."""
        self.xtal_nominal, self.ppm = xtal_hz, ppm
        self._pll_cache = [None, None]

    def configure(self, ch, freq_hz, drive=3, pll=0, enable=True):
        """Program channel `ch`. Returns the actual output frequency in Hz."""
        plan = plan_frequency(freq_hz, self.xtal_hz)
        if not enable:
            self.disable(ch)
            return plan.actual_hz
        for other, (opll, oparams) in self._active.items():
            if other != ch and opll == pll and oparams != plan.pll:
                raise ValueError(
                    f"CLK{other} already uses PLL{'AB'[pll]} at a different VCO "
                    f"frequency - move one channel to the other PLL")
        a, b, c = plan.ms
        self.bus.write(REG_MS_BASE + 8 * ch,
                       pack_params(a, b, c, plan.r_exp, plan.divby4))
        pll_changed = self._pll_cache[pll] != plan.pll
        if pll_changed:
            self.bus.write(REG_PLL_BASE[pll], pack_params(*plan.pll))
            self._pll_cache[pll] = plan.pll
        ctrl = 0x0C | (drive & 3) | (0x40 if b == 0 else 0) | (0x20 if pll else 0)
        self.bus.write(REG_CLK_CTRL + ch, [ctrl])
        if pll_changed:
            self.bus.write(REG_PLL_RESET, [0xA0])
        self._active[ch] = (pll, plan.pll)
        self._oe_off &= ~(1 << ch)
        self.bus.write(REG_OE, [self._oe_off])
        return plan.actual_hz

    def disable(self, ch):
        self._active.pop(ch, None)
        self._oe_off |= 1 << ch
        self.bus.write(REG_OE, [self._oe_off])
        self.bus.write(REG_CLK_CTRL + ch, [0x80])

    def status(self):
        """Returns dict with sys_init / lol_a / lol_b / los flags."""
        s = self.bus.read(REG_STATUS)
        return {"sys_init": bool(s & 0x80), "lol_b": bool(s & 0x40),
                "lol_a": bool(s & 0x20), "los": bool(s & 0x10)}

    def close(self):
        try:
            self.bus.write(REG_OE, [0xFF])
        except OSError:
            pass
