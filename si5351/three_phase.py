"""Three-phase output (0/120/240 deg) for Si5351, as a mixin.

Uses the phase offset registers where they reach, otherwise "walks" the phase by
briefly detuning outputs (walk.py). See Si5351.three_phase().
"""
from .constants import REG_PLL_BASE
from .planning import pack_params, phase_limits, plan_frequency


class ThreePhaseMixin:
    """Three-phase control for Si5351 (uses configure(), disable(), reset_pll(), _walk_phases()
    and the shadow state of the main class)."""

    def three_phase(self, freq_hz, reverse=False, drive=3, pll=0, off_state=0):
        """Start CLK0 / CLK1 / CLK2 as a three-phase set: 0, 120, 240 degrees (CLK1 and
        CLK2 lagging CLK0), or 0, 240, 120 with reverse=True. All on one PLL.

        Two methods, chosen automatically:
          * hardware offset - used when the phase registers can reach it (about
            9.5 MHz and up). 240 deg is made from 60 deg offset + invert, so only
            120 deg of offset range is needed. Quantised to 360/(4*N*R) degrees.
          * phase walk - at lower frequencies the offset registers are far too short
            (max ~35 ns), so CLK1/CLK2 are briefly detuned to accumulate the phase,
            see _walk_phases(). Accurate to a fraction of a degree.

        Any earlier setting of the three channels is replaced.

        Args:
            freq_hz: output frequency of all three (F_MIN..200 MHz; walk needs <= 112.5 MHz).
            reverse: swap the phase sequence (reverses the motor direction).
            drive, pll, off_state: as in configure().

        Returns:
            dict: method (str), actual_hz, phases (list of 3 achieved lag angles in degrees).

        Raises:
            ValueError: frequency out of range or the walk isn't possible.
        """
        chs = (0, 1, 2)
        phases = (0, 240, 120) if reverse else (0, 120, 240)
        plan = plan_frequency(freq_hz, self.xtal_hz, self.trim_ppm[pll])
        for ch in chs:                       # forget earlier state (also avoids PLL conflicts)
            self.disable(ch)
        self._tp = None
        # Phases >= 180 use the invert bit: offset = phase - 180. The largest offset
        # needed (120 deg) decides if the hardware registers are enough.
        offsets = [(p - 180, True) if p >= 180 else (p, False) for p in phases]
        hardware = max(o for o, _ in offsets) <= phase_limits(plan, 0)[2]
        if hardware:
            achieved = []
            for ch, (off, inv) in zip(chs, offsets):
                _, deg, _ = self.configure(ch, freq_hz, drive, pll, True, off, inv, off_state)
                achieved.append((deg + (180 if inv else 0)) % 360)
            self.reset_pll(pll)              # latch all offsets at once
            method = "hardware phase offset"
        else:
            for ch in chs:
                self.configure(ch, freq_hz, drive, pll, True, 0.0, False, off_state)
            self.reset_pll(pll)              # all three start in phase ...
            lags = self._walk_phases([(1, phases[1]), (2, phases[2])], freq_hz, pll)
            achieved = [0.0, lags[1], lags[2]]      # ... then CLK1 / CLK2 are walked
            method = "phase walk"
        self._tp = {"freq": freq_hz, "pll": pll, "chs": chs}
        return {"method": method, "actual_hz": plan.actual_hz, "phases": achieved}

    def retune_three_phase(self):
        """Re-apply the PLL setting of a running three_phase() after fine tune / ppm
        changed, without touching the channels, so their phase relation is kept.

        Returns:
            the new actual output frequency in Hz.
        """
        tp = self._tp
        pll = tp["pll"]
        plan = plan_frequency(tp["freq"], self.xtal_hz, self.trim_ppm[pll])
        if self._pll_cache[pll] != plan.pll:
            self.bus.write(REG_PLL_BASE[pll], pack_params(*plan.pll))
            self._pll_cache[pll] = plan.pll
            if pll == 0:
                self._apply_spread()
        for ch in tp["chs"]:
            self._active[ch] = (pll, plan.pll)       # set_trim / set_timing had cleared them
        return plan.actual_hz

    def three_phase_pll(self):
        """PLL used by a running three_phase(), or None."""
        return self._tp["pll"] if self._tp else None

    def stop_three_phase(self):
        """Switch the three outputs off and leave three-phase mode."""
        if self._tp:
            for ch in self._tp["chs"]:
                self.disable(ch)
        self._tp = None
