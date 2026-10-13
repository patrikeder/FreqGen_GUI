"""Pure calculations: divider planning, phase quantisation and register packing.

Nothing here talks to the chip, so it can be used (and tested) on its own.

Strategy (same as most hobby drivers, see Skyworks AN619):
  * f <= 112.5 MHz : PLL fixed at 900 MHz, fractional Multisynth, R divider
                     for outputs below 500 kHz.
  * f  > 112.5 MHz : integer Multisynth divide-by-6 (<=150 MHz) or divide-by-4
                     (<=200 MHz); the PLL VCO is then 6*f / 4*f, so that PLL
                     can't be shared with a channel needing another VCO.
"""
from dataclasses import dataclass
from fractions import Fraction

from .constants import C_DEN, F_MAX, F_MIN, PHASE_MAX_STEPS, VCO_DEFAULT


@dataclass(frozen=True)
class Plan:
    """Result of plan_frequency(): everything needed to program one output.

    pll, ms are (a, b, c) tuples meaning a + b/c. `actual_hz` is the frequency
    the chip really produces with these (quantised) dividers.
    """
    pll: tuple           # (a, b, c) PLL feedback multiplier
    ms: tuple            # (a, b, c) Multisynth divider
    r_exp: int           # output R divider = 2**r_exp
    divby4: bool
    actual_hz: float


def plan_frequency(freq_hz, xtal_hz, trim_ppm=0.0):
    """Compute PLL / Multisynth / R-divider settings for one output frequency.

    Pure function (no I2C access), so it can be used to preview a frequency.
    Uses exact Fraction arithmetic so the reported error is the true quantisation
    error and not floating-point noise.

    Args:
        freq_hz: wanted output frequency, F_MIN..F_MAX.
        xtal_hz: reference crystal frequency including any ppm correction.
        trim_ppm: fine tune of the PLL VCO; shifts the output by this many ppm.

    Returns:
        Plan with the divider values and the actual achievable frequency.

    Raises:
        ValueError: frequency out of range, or PLL multiplier outside 15..90
            (usually a wrong crystal setting).
    """
    if not F_MIN <= freq_hz <= F_MAX:
        raise ValueError(f"Frequency must be {F_MIN / 1e3:g} kHz .. {F_MAX / 1e6:g} MHz")
    f = Fraction(freq_hz)
    xtal = Fraction(xtal_hz)
    r_exp = 0
    divby4 = False
    # High band (> 112.5 MHz): a fractional divider can't reach it, so use an integer
    # divide-by-6 / divide-by-4 and let the PLL VCO follow the output (VCO = f * div).
    if f > Fraction(225, 2) * 10**6:                  # > 112.5 MHz: integer divider
        div = 4 if f > 150 * 10**6 else 6
        divby4 = div == 4
        ms = (div, 0, C_DEN)
        vco = f * div
    else:
        # Normal band: VCO fixed at 900 MHz. The Multisynth can't output below 500 kHz, so
        # raise the R divider (x2 per step, max 128) until the Multisynth output is >= 500 kHz.
        while f * 2**r_exp < 500_000 and r_exp < 7:
            r_exp += 1
        # Multisynth divider = VCO / (f * R), split into integer part a and fraction b/c.
        # b is rounded to the nearest 1/1048575 - this is the source of the small frequency error.
        ratio = Fraction(VCO_DEFAULT) / (f * 2**r_exp)
        a = int(ratio)
        b = round((ratio - a) * C_DEN)
        if b == C_DEN:
            a, b = a + 1, 0
        ms = (a, b, C_DEN)
        vco = Fraction(VCO_DEFAULT)
    # Fine tune: scaling the VCO scales the output by the same factor, and only the PLL
    # fraction has to change (the Multisynth divider stays the same).
    vco *= 1 + Fraction(trim_ppm) / 10**6
    # PLL feedback multiplier = VCO / crystal, again as a + b/c. A carry from rounding
    # (b == c) is folded into a. The chip accepts 15..90 (90 only without a fraction).
    mult = vco / xtal
    pa = int(mult)
    pb = round((mult - pa) * C_DEN)
    if pb == C_DEN:
        pa, pb = pa + 1, 0
    if not (15 <= pa <= 90) or (pa == 90 and pb):
        raise ValueError("PLL multiplier out of range - check crystal frequency")
    # Recompute the output from the rounded integers = what the chip really produces.
    vco_act = xtal * (pa + Fraction(pb, C_DEN))
    ms_val = ms[0] + Fraction(ms[1], ms[2])
    actual = float(vco_act / ms_val / 2**r_exp)
    return Plan((pa, pb, C_DEN), ms, r_exp, divby4, actual)


def phase_limits(plan, phase_deg):
    """Convert a wanted output phase into the chip's CLKx_PHOFF register value.

    The offset register counts in units of Tvco/4, so one step is
    360 / (4 * N * R) degrees of the output (N = Multisynth divide, R = R divider).
    The register is 7 bit, so at most 127 steps are possible; larger requests are
    clamped. Phase is only meaningful between outputs sharing one PLL and one
    frequency.

    Args:
        plan: Plan of the channel (from plan_frequency).
        phase_deg: wanted phase, any angle (wrapped to 0..360).

    Returns:
        (register_steps, quantised_degrees, maximum_degrees)
    """
    # N = effective Multisynth divide including its fractional part. One register step
    # is Tvco/4, i.e. 360 / (4 * N * R) degrees of the output period (N * R * Tvco).
    n = plan.ms[0] + Fraction(plan.ms[1], plan.ms[2])
    deg_per_step = float(Fraction(360) / (4 * n * 2**plan.r_exp))
    steps = min(round((phase_deg % 360) / deg_per_step), PHASE_MAX_STEPS)
    return steps, steps * deg_per_step, PHASE_MAX_STEPS * deg_per_step


def pll_value(params):
    """Numeric value a + b/c of a PLL parameter tuple (Fraction)."""
    return params[0] + Fraction(params[1], params[2])


def pack_params(a, b, c, r_exp=0, divby4=False):
    """Encode a divider a + b/c into the 8 register bytes of a PLL / Multisynth block.

    Implements the P1/P2/P3 formulas of AN619:
        P1 = 128*a + floor(128*b/c) - 512,  P2 = 128*b - c*floor(128*b/c),  P3 = c
    Multisynth blocks also carry the R divider (bits 6:4 of byte 2) and the
    divide-by-4 flag; for PLL blocks leave r_exp=0 / divby4=False.

    Args:
        a, b, c: integer part, numerator, denominator (c <= 1048575).
        r_exp: output R divider as exponent, R = 2**r_exp (0..7).
        divby4: True for the special Multisynth divide-by-4 mode (needed > 150 MHz).

    Returns:
        List of 8 bytes, to be written starting at the block's base register.
    """
    # P1/P2/P3 as defined in AN619 (see docstring).
    x = (128 * b) // c
    p1 = 128 * a + x - 512
    p2 = 128 * b - c * x
    p3 = c
    # Divide-by-4 mode (outputs > 150 MHz) ignores the normal encoding: P1 = P2 = 0 and
    # P3 = 1, together with the DIVBY4 bits (0x0C) set in byte 2 below.
    if divby4:
        p1 = p2 = 0
        p3 = 1
    # Byte layout: P3[15:8], P3[7:0], R_DIV<<4 | DIVBY4<<2 | P1[17:16], P1[15:8],
    # P1[7:0], P3[19:16]<<4 | P2[19:16], P2[15:8], P2[7:0]. (PLL blocks use only P1[17:16] in byte 2.)
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
