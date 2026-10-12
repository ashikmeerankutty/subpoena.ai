from __future__ import annotations

from collections.abc import Iterator

import pytest

from apitest import Env, _env


@pytest.fixture
def env() -> Iterator[Env]:
    yield from _env()
