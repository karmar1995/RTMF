import random
import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class LatencyProfileMs:
    """
    Piecewise latency model in milliseconds:
      - base: typical calls
      - mid:  moderate jitter
      - spike: rare spikes
    Probabilities must sum to 1.0.
    """
    p_base: float = 0.90
    base_min: float = 2.0
    base_max: float = 4.0

    p_mid: float = 0.09
    mid_min: float = 4.0
    mid_max: float = 8.0

    p_spike: float = 0.01
    spike_min: float = 10.0
    spike_max: float = 20.0

    def validate(self) -> None:
        total = self.p_base + self.p_mid + self.p_spike
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"Probabilities must sum to 1.0, got {total:.6f}.")
        for lo, hi, name in [
            (self.base_min, self.base_max, "base"),
            (self.mid_min, self.mid_max, "mid"),
            (self.spike_min, self.spike_max, "spike"),
        ]:
            if lo < 0 or hi < 0 or hi < lo:
                raise ValueError(f"Invalid range for {name}: [{lo}, {hi}].")


class RestLatencyEmulator:
    """
    Drop-in latency emulator for "bus" calls to your use-case layer.

    Typical integration:
        emulator = RestLatencyEmulator(enabled=True)
        ...
        emulator.sleep()  # call right before/after the bus invocation

    Notes:
    - Uses its own RNG so you can seed it for reproducible tests.
    - Returns the slept duration (ms) if you want metrics/logging.
    """

    def __init__(
        self,
        profile: LatencyProfileMs = LatencyProfileMs(),
        *,
        enabled: bool = True,
        seed: Optional[int] = None,
    ) -> None:
        profile.validate()
        self._profile = profile
        self._enabled = enabled
        self._rng = random.Random(seed)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def set_profile(self, profile: LatencyProfileMs) -> None:
        profile.validate()
        self._profile = profile

    def sample_ms(self) -> float:
        """
        Sample the next latency in ms (does not sleep).
        """
        p = self._profile
        r = self._rng.random()

        if r < p.p_base:
            return self._rng.uniform(p.base_min, p.base_max)
        elif r < p.p_base + p.p_mid:
            return self._rng.uniform(p.mid_min, p.mid_max)
        else:
            return self._rng.uniform(p.spike_min, p.spike_max)

    def sleep(self) -> float:
        """
        Sleep according to the latency model. Returns slept time in ms.
        If disabled, returns 0.0 without sleeping.
        """
        if not self._enabled:
            return 0.0

        ms = self.sample_ms()
        time.sleep(ms / 1000.0)
        return ms

    def __call__(self) -> float:
        """
        Convenience: emulator() == emulator.sleep()
        """
        return self.sleep()
