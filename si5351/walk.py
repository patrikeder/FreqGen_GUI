"""Phase "walking": shift outputs against each other by briefly detuning them.

The phase offset registers reach only ~35 ns, so below ~9.5 MHz a 120 degree shift is out
of range. Phase is the integral of the frequency difference, so running an output
`rate` Hz slower than the others for t seconds delays it by rate*t cycles. This works at
any frequency up to 112.5 MHz and is used by the three-phase mode and the phase sweep.
"""
import time
from time import perf_counter

from .constants import F_MAX, F_MIN, PHASE_STEP_WALK, REG_CLK_CTRL, REG_MS_BASE, T_WALK
from .planning import pack_params, plan_frequency


class WalkMixin:
    """Phase walking for Si5351 (uses self.bus, self._ctrl, self.xtal_hz, self.trim_ppm)."""

    def _plan_walk(self, base, base_hz, lag, duration, pll):
        """Choose the detuned frequency that moves an output by `lag` degrees.

        Tries the shortest way round first (> 180 deg = run faster, i.e. lead). If the
        detuned frequency would leave F_MIN..F_MAX (e.g. base 3.5 kHz) it goes the other
        way round. If the divider resolution is too coarse for the wanted small detune
        (high frequencies) the detune is doubled until the output really changes.

        Args:
            base: Plan of the common frequency.
            base_hz: that frequency.
            lag: wanted lag in degrees, -180..180 (negative = lead).
            duration: wanted time in seconds the output is detuned.
            pll: PLL of the channel.

        Returns:
            (lag actually planned, Plan of the detuned frequency, rate in cycles/s).

        Raises:
            ValueError: walking isn't possible (VCO would have to move, > 112.5 MHz).
        """
        for lag_try in (lag, lag - 360 if lag > 0 else lag + 360):
            delta = abs(lag_try) / 360 / duration
            for _ in range(16):
                walk_hz = base_hz - delta if lag_try > 0 else base_hz + delta
                if not F_MIN <= walk_hz <= F_MAX:
                    break
                walk = plan_frequency(walk_hz, self.xtal_hz, self.trim_ppm[pll])
                rate = base.actual_hz - walk.actual_hz           # cycles of lag per second
                if walk.pll != base.pll:
                    raise ValueError("Phase walk not possible above 112.5 MHz")
                if rate * lag_try > 0:
                    return lag_try, walk, rate
                delta *= 2
        raise ValueError("Phase walk not possible at this frequency")

    def _walk_phases(self, jobs, base_hz, pll, duration=T_WALK, restore=True):
        """Delay outputs by briefly running them at a slightly different frequency.

        With dividers known exactly, the delay is set by time, not by the I2C or
        scheduler latency: start and end writes have the same latency, which cancels,
        leaving only jitter (~0.1 ms) times a rate of ~1 Hz, i.e. ~0.1 deg. All outputs
        of `jobs` are detuned at once so the whole alignment takes about `duration`.

        Needs the outputs already running at `base_hz` on one PLL whose VCO doesn't
        change with frequency (base_hz <= 112.5 MHz).

        Args:
            jobs: list of (channel, lag_degrees), lag 0..360 (> 180 = lead the short way).
            base_hz: the common output frequency.
            pll: PLL of those channels.
            duration: seconds the outputs are detuned (more = more accurate, slower).
            restore: put the clock control registers back afterwards. A sweep passes
                False and calls restore_ctrl() at its end, to avoid toggling integer mode
                around every step.

        Returns:
            dict channel -> achieved lag in degrees (0..360), from the measured time.
        """
        base = plan_frequency(base_hz, self.xtal_hz, self.trim_ppm[pll])
        entries = []
        for ch, phase in jobs:
            lag = phase if phase <= 180 else phase - 360
            lag, walk, rate = self._plan_walk(base, base_hz, lag, duration, pll)
            entries.append({
                "ch": ch, "rate": rate, "t_req": abs(lag) / 360 / abs(rate),
                "walk": pack_params(*walk.ms, walk.r_exp, walk.divby4),
                "base": pack_params(*base.ms, base.r_exp, base.divby4),
                "ctrl": self._ctrl[ch]})
        # Fractional Multisynth mode while detuned (integer mode would reject the fraction).
        for e in entries:
            self.bus.write(REG_CLK_CTRL + e["ch"], [e["ctrl"] & ~0x40])
        # Start: detune every job, remembering when (just before the write, see docstring).
        for e in entries:
            e["t0"] = perf_counter()
            self.bus.write(REG_MS_BASE + 8 * e["ch"], e["walk"])
        # End: in order of due time, sleep most of the wait and spin for the last 3 ms,
        # then write the base divider back and compute the phase from the measured time.
        lags = {}
        for e in sorted(entries, key=lambda e: e["t0"] + e["t_req"]):
            due = e["t0"] + e["t_req"]
            if due - perf_counter() > 0.003:
                time.sleep(due - perf_counter() - 0.003)
            while perf_counter() < due:
                pass
            t1 = perf_counter()
            self.bus.write(REG_MS_BASE + 8 * e["ch"], e["base"])
            lags[e["ch"]] = (e["rate"] * (t1 - e["t0"]) * 360) % 360
        if restore:
            self.restore_ctrl([e["ch"] for e in entries])
        return lags

    def walk_phase(self, ch, base_hz, delta_deg, pll, duration=PHASE_STEP_WALK):
        """Shift output `ch` by `delta_deg` against the other outputs of its PLL.

        One step of a phase sweep: positive = delay (lag), negative = advance. Leaves the
        channel in fractional Multisynth mode; call restore_ctrl() when the sweep ends.

        Args:
            ch: channel to shift (running at base_hz, same PLL as its reference).
            base_hz: the common frequency of the channel and its reference.
            delta_deg: wanted shift, -180..180.
            pll: PLL of the channel.
            duration: seconds spent detuned; the default (20 ms) keeps steps quick.

        Returns:
            the shift actually made, in degrees (signed), from the measured time.
        """
        if abs(delta_deg) < 0.005:
            return 0.0
        lag = self._walk_phases([(ch, delta_deg % 360)], base_hz, pll, duration, False)[ch]
        return lag - 360 if lag > 180 else lag

    def restore_ctrl(self, chs):
        """Write the normal clock control byte (incl. integer mode) of channels `chs`."""
        for ch in chs:
            self.bus.write(REG_CLK_CTRL + ch, [self._ctrl[ch]])
