"""Shared isolation for process-local AI state."""

from __future__ import annotations

import pytest

from celestai.ai.cache import response_cache


@pytest.fixture(autouse=True)
def reset_ai_response_cache():
    response_cache.reset()
    yield
    response_cache.reset()
