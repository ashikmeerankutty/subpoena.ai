from __future__ import annotations

import pytest

from courtkit import Harness


@pytest.fixture
def h() -> Harness:
    return Harness()
