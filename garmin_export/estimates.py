"""Download estimates based on missing payloads and measured request work."""

from dataclasses import dataclass


def expected_request_wait(interval: float, delay: float, jitter: float) -> float:
    """Mean of max(interval, delay + uniform(0, jitter)), not their sum."""
    if interval <= delay:
        return delay + jitter / 2
    upper = delay + jitter
    if interval >= upper:
        return interval
    return interval + (upper - interval) ** 2 / (2 * jitter)


@dataclass
class DownloadEstimate:
    remaining_requests: int
    expected_wait_seconds: float
    completed_requests: int = 0
    elapsed_seconds: float = 0.0

    def record_completed(self, elapsed_seconds: float) -> None:
        self.remaining_requests = max(0, self.remaining_requests - 1)
        self.completed_requests += 1
        self.elapsed_seconds += max(0.0, elapsed_seconds)

    def discard_requests(self, count: int) -> None:
        """Remove requests abandoned for a failed activity in this run."""
        self.remaining_requests = max(0, self.remaining_requests - count)

    def remaining_seconds(self) -> float:
        per_request = (
            self.elapsed_seconds / self.completed_requests
            if self.completed_requests
            else self.expected_wait_seconds
        )
        return self.remaining_requests * per_request
