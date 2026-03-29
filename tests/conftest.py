"""Pytest configuration for CodeSpace tests."""
import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: marks tests that call AgentCore Runtime/Memory (may take 30-180s)")


def pytest_collection_modifyitems(config, items):
    """Auto-skip slow tests unless explicitly requested."""
    if config.getoption("-m"):
        return  # User specified markers, respect their choice
    # By default, run everything
