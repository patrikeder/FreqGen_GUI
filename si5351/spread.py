"""Spread spectrum on PLL A (AN619 section 5): register maths and the driver mixin."""
from fractions import Fraction

from .constants import REG_SSC, SSC_MAX_PCT, SSC_MIN_PCT, SSC_MOD_HZ
from .planning import pll_value


def spread_registers(pll_params, xtal_hz, percent, center):
    """Registers 149..161 for spread spectrum on PLL A, following AN619 section 5.

    The PLL VCO is modulated at ~31.5 kHz: it ramps up/down by `percent` of its
    frequency in SSUDP steps per half period, each step being SSDN / SSUP in
    PLL-multiplier units.

    Args:
        pll_params: (a, b, c) PLL A multiplier currently programmed.
        xtal_hz: PLL input frequency (fPFD).
        percent: spread amplitude, SSC_MIN_PCT..SSC_MAX_PCT[center].
        center: True for +/- percent around the nominal frequency, False for
            down spread (0 .. -percent).

    Returns:
        13 bytes for registers 149..161 with SSC_EN still 0 (the caller sets bit 7
        of register 149 after the parameters are in place).
    """
    amp = Fraction(percent) / 100
    mult = pll_value(pll_params)
    ssudp = int(Fraction(xtal_hz) / (4 * SSC_MOD_HZ))            # steps per quarter period
    k = 128 if center else 64
    ssdn = k * mult * amp / ((1 + amp) * ssudp)                  # step size going down
    dn1 = int(ssdn)
    dn2 = int(32767 * (ssdn - dn1))
    if center:
        ssup = 128 * mult * amp / ((1 - amp) * ssudp)            # step size going up
        up1 = int(ssup)
        up2 = int(32767 * (ssup - up1))
        up3 = 32767
    else:
        up1, up2, up3 = 0, 0, 1                                  # down spread: no up ramp
    return [
        (dn2 >> 8) & 0x7F, dn2 & 0xFF,                           # 149 (SSC_EN=0), 150
        (0x80 if center else 0) | ((32767 >> 8) & 0x7F), 32767 & 0xFF,   # 151 mode+P3, 152
        dn1 & 0xFF,                                              # 153
        ((ssudp >> 8) & 0x0F) << 4 | ((dn1 >> 8) & 0x0F),        # 154
        ssudp & 0xFF,                                            # 155
        (up2 >> 8) & 0x7F, up2 & 0xFF,                           # 156, 157
        (up3 >> 8) & 0x7F, up3 & 0xFF,                           # 158, 159
        up1 & 0xFF,                                              # 160
        (up1 >> 8) & 0x0F,                                       # 161 (SS_NCLK must be 0)
    ]



class SpreadMixin:
    """Spread spectrum control for Si5351 (uses self.bus, self._pll_cache, self.xtal_hz)."""

    def set_spread(self, percent=0.0, center=False):
        """Enable (percent > 0) or disable spread spectrum on PLL A.

        The modulation (~31.5 kHz) applies to every output running from PLL A.
        It is recalculated automatically whenever PLL A is reprogrammed. If no
        channel has used PLL A yet it is applied as soon as one does.

        Args:
            percent: amplitude in %, 0 = off. Down spread 0.1..2.5, center 0.1..1.5.
            center: True = +/- percent around the nominal frequency, False = down.

        Raises:
            ValueError: amplitude outside the chip's range.
        """
        if percent <= 0:
            self._ssc = None
            self.bus.write(REG_SSC, [0x00])
            return
        if not SSC_MIN_PCT <= percent <= SSC_MAX_PCT[center]:
            raise ValueError(f"Spread must be {SSC_MIN_PCT:g}..{SSC_MAX_PCT[center]:g} % "
                             f"for {'center' if center else 'down'} spread")
        self._ssc = (percent, center)
        self._apply_spread()

    def _apply_spread(self):
        """Program the spread registers from the PLL A multiplier now in the chip."""
        if self._ssc is None or self._pll_cache[0] is None:
            return
        regs = spread_registers(self._pll_cache[0], self.xtal_hz, *self._ssc)
        self.bus.write(REG_SSC, regs)                      # parameters first, SSC_EN = 0
        self.bus.write(REG_SSC, [regs[0] | 0x80])          # then switch spreading on
