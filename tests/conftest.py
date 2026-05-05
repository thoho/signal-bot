"""Test-suite-wide fixtures.

The retry helper sleeps with exponential backoff between attempts to avoid
hammering an already-struggling upstream. In tests we want the retry
*logic* to run but not the wall-clock waits, so zero out the backoff.
"""

import pytest

from app import _retry


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_retry, "_backoff_seconds", lambda attempt, base: 0.0)
