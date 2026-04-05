"""Pytest configuration and shared fixtures.

Provides common test fixtures, configuration, and utilities for the test suite.
Includes setup/teardown logic and mock objects used across multiple test modules.
"""

from typing import Iterator

import pytest

from boomarr import config as config_module


@pytest.fixture(autouse=True)
def reset_config() -> Iterator[None]:
    """Reset the global config singleton before every test."""
    config_module._config = None
    yield
    config_module._config = None
