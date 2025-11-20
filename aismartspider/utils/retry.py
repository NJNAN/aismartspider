"""Basic retry policy helper."""

from __future__ import annotations

import time
from typing import Callable, TypeVar

T = TypeVar("T")


class RetryPolicy:
    """Simple exponential backoff retry wrapper."""

    def __init__(self, max_retries: int = 3, backoff: float = 1.5) -> None:
        self.max_retries = max_retries
        self.backoff = backoff

    def run(self, func: Callable[[], T]) -> T:
        delay = 1.0
        for attempt in range(self.max_retries):
            try:
                return func()
            except Exception:
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(delay)
                delay *= self.backoff
