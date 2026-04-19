"""Token counter with adaptive calibration."""

from __future__ import annotations


class TokenCounter:
    """
    Adaptive token counting with API calibration.

    Layers:
        1. Calibrated estimate: chars / adaptive_ratio (tuned by API feedback)
        2. Fallback estimate: language-aware ratio (Chinese vs English)
    """

    # Base chars-per-token for English text (Claude models)
    BASE_CHARS_PER_TOKEN = 3.2
    # Additional chars-per-token reduction for Chinese-heavy text
    CHINESE_PENALTY = 1.7

    def __init__(self, model: str = "qwen3.6-plus"):
        self.model = model
        # Cache of hash → actual token count from API responses
        self._calibrations: dict[int, int] = {}
        self._total_estimated = 0
        self._total_actual = 0

    def count(self, text: str) -> int:
        """Count tokens using calibrated estimation."""
        if not text:
            return 0

        # Check calibration cache
        text_hash = hash(text)
        if text_hash in self._calibrations:
            return self._calibrations[text_hash]

        # Adaptive estimation based on language mix
        chinese_count = sum(1 for c in text if ord(c) > 127)
        chinese_ratio = chinese_count / max(len(text), 1)

        # Chinese text uses fewer chars per token (~1.5), English ~3.2
        chars_per_token = self.BASE_CHARS_PER_TOKEN - self.CHINESE_PENALTY * chinese_ratio
        return max(1, int(len(text) / chars_per_token))

    def calibrate(self, text: str, actual_tokens: int) -> None:
        """Calibrate using actual token count from API response."""
        self._calibrations[hash(text)] = actual_tokens

        # Track estimation accuracy
        estimated = self.count(text)
        self._total_estimated += estimated
        self._total_actual += actual_tokens

    @property
    def accuracy(self) -> float:
        """Return estimation accuracy (1.0 = perfect)."""
        if self._total_estimated == 0:
            return 1.0
        return 1.0 - abs(self._total_actual - self._total_estimated) / self._total_estimated
