"""Fixtures for EMT Madrid tests."""

import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from homeassistant.core import State

pytest_plugins = ["pytest_asyncio"]


class MockStates:
    """Mock for Home Assistant states."""

    def __init__(self):
        self._states = {}

    def get(self, entity_id):
        return self._states.get(entity_id)

    def async_set(self, entity_id, state, attributes=None):
        mock_state = MagicMock(spec=State)
        mock_state.state = state
        mock_state.attributes = attributes or {}
        self._states[entity_id] = mock_state


@pytest.fixture
def hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.states = MockStates()
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(return_value=[])
    hass.services = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.services.async_register = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda f, *args: f(*args))
    hass.async_create_task = MagicMock()
    return hass


@pytest.fixture
def mock_api_request():
    """Create a mock for API requests."""
    with patch(
        "custom_components.emt_madrid.emt_madrid.APIEMT._make_request"
    ) as mock:
        yield mock
