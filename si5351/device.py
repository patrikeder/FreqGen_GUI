"""The Si5351 class: initialisation, per-channel configuration and status.

Spread spectrum, three-phase mode and phase walking live in mixins (spread.py,
three_phase.py, walk.py).
"""
import time
from fractions import Fraction

from .constants import (REG_CLK_CTRL, REG_DIS_STATE, REG_FANOUT, REG_MS_BASE,
                        REG_OE, REG_PHASE, REG_PLL_BASE, REG_PLL_RESET, REG_SSC, REG_STATUS,
                        REG_XTAL_LOAD, TRIM_MAX_PPM)
from .planning import pack_params, phase_limits, plan_frequency, pll_value
from .spread import SpreadMixin
from .three_phase import ThreePhaseMixin
from .walk import WalkMixin


class Si5351(SpreadMixin, ThreePhaseMixin, WalkMixin):
    """High level control of the three SI5351A outputs.

    Typical use:
        dev = Si5351(I2CBus(1))
        dev.configure(0, 10e6)                  # CLK0 = 10 MHz on PLL A
        dev.configure(1, 10e6, phase_deg=90)    # CLK1 = 10 MHz, 90 deg after CLK0
        dev.disable(0)

    The class caches what was written to the PLLs / phase registers so that
    repeated calls (e.g. a frequency sweep) only touch the registers that changed
    and only reset a PLL when needed.
    """
    NUM_CH = 3

    def __init__(self, bus, xtal_hz=25_000_000, ppm=0.0, load_pf=10):
        """Initialise the chip: wait for SYS_INIT, disable and power down all outputs,
        set the crystal load capacitance (6, 8 or 10 pF).

        Args:
            bus: I2CBus or SimBus.
            xtal_hz: nominal crystal frequency (25 or 27 MHz on SI5351A).
            ppm: crystal error correction, see `xtal_hz` property.
            load_pf: crystal load capacitance, must match the crystal.
        """
        self.bus = bus
        self.xtal_nominal = xtal_hz
        self.ppm = ppm
        # Shadow copy of what the chip currently holds, so unchanged registers aren't
        # rewritten and PLLs are only reset when really necessary.
        self._pll_cache = [None, None]
        self._phase_cache = {}             # ch -> programmed PHOFF
        self._active = {}                  # ch -> (pll_index or None, pll_params)
        self._pll_val = [None, None]       # numeric PLL multipliers, for the reset decision
        self._oe_off = 0xFF
        self._dis_reg = 0                  # shadow of register 24 (disable states)
        self.trim_ppm = [0.0, 0.0]         # fine tune per PLL, see set_trim()
        self._ssc = None                   # (percent, center) while spread is enabled
        self._ctrl = {}                    # ch -> clock control byte last written
        self._tp = None                    # dict while three_phase() is running
        # Safe start-up: wait for the chip to finish loading, switch every output off and
        # power it down, then set the crystal load capacitance.
        self._wait_ready()
        bus.write(REG_OE, [0xFF])
        bus.write(REG_CLK_CTRL, [0x80] * 8)                    # power down all
        bus.write(REG_FANOUT, [0xD0])          # route crystal / Multisynth to the output muxes
        bus.write(REG_DIS_STATE, [0x00])       # disabled outputs go low
        bus.write(REG_SSC, [0x00])             # spread spectrum off
        bus.write(REG_XTAL_LOAD, [{6: 0x52, 8: 0x92, 10: 0xD2}[load_pf]])


    @property
    def simulated(self):
        """True when running on SimBus (no real hardware)."""
        return getattr(self.bus, "simulated", False)


    @property
    def xtal_hz(self):
        """Effective reference frequency = nominal * (1 + ppm*1e-6).

        All dividers are calculated from this value, so entering the measured
        crystal error as ppm makes the outputs accurate in absolute terms.
        """
        return self.xtal_nominal * (1 + self.ppm * 1e-6)


    def _wait_ready(self):
        """Block (max 0.5 s) until the chip clears SYS_INIT after power-up."""
        for _ in range(50):
            # Poll every 10 ms; SYS_INIT (bit 7 of register 0) stays 1 while the chip boots.
            if not self.bus.read(REG_STATUS) & 0x80:   # SYS_INIT
                return
            time.sleep(0.01)


    def set_timing(self, xtal_hz, ppm):
        """Change crystal frequency / ppm correction.

        A new nominal crystal frequency invalidates the PLL and phase caches so the
        next configure() rewrites everything (with PLL reset). A pure ppm change is
        a small retune and keeps them, so it is glitch free like set_trim().
        The caller must re-apply all active channels afterwards (the GUI does this
        in App.apply_reference); the active list is cleared here so the re-apply
        of the channels sharing a PLL isn't mistaken for a VCO conflict.
        """
        if xtal_hz != self.xtal_nominal:
            self._pll_cache = [None, None]
            self._pll_val = [None, None]
            self._phase_cache.clear()
        self.xtal_nominal, self.ppm = xtal_hz, ppm
        self._active.clear()


    def set_trim(self, pll, ppm):
        """Fine tune PLL `pll` (0 = A, 1 = B) by `ppm` (+/- TRIM_MAX_PPM).

        Shifts every output running from that PLL by the same relative amount, in
        steps of ~0.03 ppm (the PLL fraction resolution), without resetting the PLL.
        Useful to lock to a reference or for slow FM. The caller must re-apply the
        active channels of that PLL afterwards (GUI: App.apply_trim).

        Raises:
            ValueError: ppm outside the allowed range.
        """
        if abs(ppm) > TRIM_MAX_PPM:
            raise ValueError(f"Fine tune must be within +/-{TRIM_MAX_PPM:g} ppm")
        self.trim_ppm[pll] = ppm
        for ch in [c for c, (p, _) in self._active.items() if p == pll]:
            del self._active[ch]


    def set_off_state(self, ch, state):
        """Choose what output `ch` does while disabled: 0 = low, 1 = high, 2 = Hi-Z.

        Written to register 24 only when it differs from the current setting.
        """
        reg = (self._dis_reg & ~(3 << 2 * ch)) | (state << 2 * ch)
        if reg != self._dis_reg:
            self.bus.write(REG_DIS_STATE, [reg])
            self._dis_reg = reg


    def configure(self, ch, freq_hz, drive=3, pll=0, enable=True, phase_deg=0.0,
                  invert=False, off_state=0, xtal_out=False):
        """Set frequency, drive, PLL, phase, polarity and on/off state of one output.

        Sequence: Multisynth block -> phase offset -> PLL block (only if it
        changed) -> clock control -> PLL reset (only if PLL or phase changed, it
        latches the phase offsets and restarts all outputs of that PLL together)
        -> output enable. With enable=False the channel is switched off instead.

        Phase is relative to other channels on the same PLL running at the same
        frequency; it is quantised to 360/(4*N*R) degrees (N = Multisynth divide,
        R = output divider) and limited to 127 steps (see phase_limits).

        Args:
            ch: output number 0..2.
            freq_hz: wanted frequency in Hz.
            drive: output current index 0..3 = 2/4/6/8 mA (see DRIVE_MA).
            pll: 0 = PLL A, 1 = PLL B.
            enable: False just disables the output.
            phase_deg: wanted phase offset in degrees.
            invert: invert the output (extra 180 deg, any frequency).
            off_state: level while disabled, 0 low / 1 high / 2 Hi-Z (OFF_STATES).
            xtal_out: output the crystal frequency directly (bypasses PLL, Multisynth
                and phase; freq_hz, pll and phase_deg are ignored).

        Returns:
            (actual_hz, actual_phase_deg, max_phase_deg)

        Raises:
            ValueError: frequency out of range, or another active channel on the
                same PLL needs a different VCO frequency (only happens > 112.5 MHz).
            OSError: I2C failure.
        """
        self.set_off_state(ch, off_state)
        # Crystal passthrough: clock source 00 = crystal. No PLL involved, so the channel
        # takes no part in the PLL conflict check below.
        if xtal_out:
            if not enable:
                self.disable(ch)
            else:
                self.bus.write(REG_CLK_CTRL + ch, [(drive & 3) | (0x10 if invert else 0)])
                self._active[ch] = (None, None)
                self._phase_cache.pop(ch, None)
                self._oe_off &= ~(1 << ch)
                self.bus.write(REG_OE, [self._oe_off])
            return self.xtal_hz, 0.0, 0.0
        plan = plan_frequency(freq_hz, self.xtal_hz, self.trim_ppm[pll])
        # Switch-off request: disable the output, but still report the values this
        # frequency / phase would give so the GUI can display them.
        if not enable:
            self.disable(ch)
            return (plan.actual_hz, *phase_limits(plan, phase_deg)[1:])
        # Channels on one PLL share its VCO. Retuning it for this channel would shift the
        # other active channels, so refuse and tell the user to use the other PLL.
        for other, (opll, oparams) in self._active.items():
            if other != ch and opll == pll and oparams != plan.pll:
                raise ValueError(
                    f"CLK{other} already uses PLL{'AB'[pll]} at a different VCO "
                    f"frequency - move one channel to the other PLL")
        # 1) Multisynth divider and R divider of this channel.
        a, b, c = plan.ms
        self.bus.write(REG_MS_BASE + 8 * ch,
                       pack_params(a, b, c, plan.r_exp, plan.divby4))
        # 2) Phase offset register - written only if it differs from what the chip has.
        steps, actual_deg, max_deg = phase_limits(plan, phase_deg)
        phase_changed = self._phase_cache.get(ch) != steps
        if phase_changed:
            self.bus.write(REG_PHASE + ch, [steps])
            self._phase_cache[ch] = steps
        # 3) PLL multiplier - written only if it changed, so a shared PLL isn't disturbed.
        pll_changed = self._pll_cache[pll] != plan.pll
        # A VCO move of < 0.1 % (fine tune, ppm change, sweep step) needs no PLL reset: the
        # PLL just follows. Bigger moves and the first start need one to recalibrate.
        old_val = self._pll_val[pll]
        new_val = pll_value(plan.pll)
        pll_reset = old_val is None or abs(new_val - old_val) / old_val > Fraction(1, 1000)
        if pll_changed:
            self.bus.write(REG_PLL_BASE[pll], pack_params(*plan.pll))
            self._pll_cache[pll] = plan.pll
            if pll_reset:
                self._pll_val[pll] = new_val
            if pll == 0:
                self._apply_spread()        # spread step sizes depend on the PLL A multiplier
        # 4) Clock control: 0x0C = powered up with the Multisynth as source, bit 6 = integer
        # mode (used when b == 0, lowest jitter), bit 5 = PLL B, bit 4 = invert,
        # bits 1:0 = drive current.
        ctrl = (0x0C | (drive & 3) | (0x40 if b == 0 else 0) | (0x20 if pll else 0)
                | (0x10 if invert else 0))
        self.bus.write(REG_CLK_CTRL + ch, [ctrl])
        self._ctrl[ch] = ctrl
        if (pll_changed and pll_reset) or phase_changed:   # reset latches the phase offsets
            self.bus.write(REG_PLL_RESET, [0x80 if pll else 0x20])
        # 5) Remember the channel and finally release its output-disable bit.
        self._active[ch] = (pll, plan.pll)
        self._oe_off &= ~(1 << ch)
        self.bus.write(REG_OE, [self._oe_off])
        return plan.actual_hz, actual_deg, max_deg


    def reset_pll(self, pll):
        """Reset PLL `pll`: all its Multisynths restart together, which re-latches the
        phase offsets and makes outputs with identical dividers start in phase.
        Interrupts every output running from that PLL for a moment."""
        self.bus.write(REG_PLL_RESET, [0x80 if pll else 0x20])


    def disable(self, ch):
        """Switch output `ch` off by setting its OE bit; the pin then takes the level
        chosen with set_off_state() (low by default).

        The driver stays powered so that level is actually driven. Forgets the
        channel's phase setting, so enabling it again re-latches the phase with a
        PLL reset and it restarts aligned with the other channels.
        """
        self._active.pop(ch, None)
        self._phase_cache.pop(ch, None)
        self._oe_off |= 1 << ch
        self.bus.write(REG_OE, [self._oe_off])


    def status(self):
        """Read status register 0.

        Returns:
            dict of booleans: sys_init (still starting), lol_a / lol_b (PLL A / B
            lost lock) and los (no signal from the crystal).
        """
        # Register 0 bits: 7 SYS_INIT, 6 LOL_B, 5 LOL_A, 4 LOS (1 = condition present).
        s = self.bus.read(REG_STATUS)
        return {"sys_init": bool(s & 0x80), "lol_b": bool(s & 0x40),
                "lol_a": bool(s & 0x20), "los": bool(s & 0x10)}


    def close(self):
        """Disable all outputs (call before exiting). Ignores I2C errors."""
        try:
            self.bus.write(REG_OE, [0xFF])
        except OSError:
            pass
