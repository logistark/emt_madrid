"""Tests for the EMT Madrid integration."""

from unittest.mock import patch, MagicMock
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_RADIUS, CONF_LATITUDE, CONF_LONGITUDE

from custom_components.emt_madrid import DOMAIN, CONF_STOPS
from custom_components.emt_madrid.config_flow import EMTMadridConfigFlow


# Mock API responses
VALID_LOGIN = {
    "code": "01",
    "description": "Token extended OK",
    "datetime": "2023-06-29T19:50:08.307475",
    "data": [
        {
            "accessToken": "3bd5855a-ed3d-41d5-8b4b-182726f86031",
            "email": "test@mail.com",
        }
    ],
}

INVALID_LOGIN = {
    "code": "92",
    "description": "Error: User not found",
    "datetime": "2023-06-29T20:01:09.441986",
    "data": [],
}

VALID_NEARBY_STOPS = {
    "code": "00",
    "description": "Data recovered OK",
    "data": [
        {
            "stop": "72",
            "stopName": "Cibeles-Casa de América",
            "distance": 150,
            "lines": [{"label": "27"}, {"label": "5"}]
        },
        {
            "stop": "73",
            "stopName": "Recoletos",
            "distance": 280,
            "lines": [{"label": "14"}]
        }
    ],
}

VALID_ARRIVALS = {
    "code": "00",
    "description": "Data recovered OK",
    "data": [
        {
            "Arrive": [
                {
                    "line": "27",
                    "stop": "72",
                    "destination": "PLAZA CASTILLA",
                    "estimateArrive": 180,
                    "DistanceBus": 674,
                },
                {
                    "line": "5",
                    "stop": "72",
                    "destination": "CHAMARTIN",
                    "estimateArrive": 420,
                    "DistanceBus": 1200,
                },
            ],
        }
    ],
}


def make_request_mock(url, headers=None, data=None, method="POST"):
    """Mock the API request."""
    if "login" in url:
        if headers and headers.get("email") == "invalid@email.com":
            return INVALID_LOGIN
        return VALID_LOGIN
    if "arroundxy" in url:
        return VALID_NEARBY_STOPS
    if "arrives" in url:
        return VALID_ARRIVALS
    return {"code": "00", "data": []}


class TestConfigFlow:
    """Test the config flow."""

    def _init_flow(self, hass):
        """Initialize a config flow with proper context."""
        flow = EMTMadridConfigFlow()
        flow.hass = hass
        flow.context = {}
        flow._async_current_entries = lambda: []
        flow._abort_if_unique_id_configured = lambda: None
        return flow

    @patch(
        "custom_components.emt_madrid.config_flow.APIEMT._make_request",
        side_effect=make_request_mock,
    )
    async def test_user_flow_success(self, mock_request, hass: HomeAssistant) -> None:
        """Test successful user config flow."""
        # Set up zone.home
        hass.states.async_set(
            "zone.home",
            "zoning",
            {"latitude": 40.4168, "longitude": -3.7038}
        )

        flow = self._init_flow(hass)

        result = await flow.async_step_user(
            user_input={
                CONF_EMAIL: "test@mail.com",
                CONF_PASSWORD: "password123",
                CONF_RADIUS: 300,
                CONF_STOPS: "",
            }
        )

        assert result["type"].value == "create_entry"
        assert result["title"] == "EMT Madrid"
        assert result["data"][CONF_EMAIL] == "test@mail.com"
        assert result["data"][CONF_RADIUS] == 300

    @patch(
        "custom_components.emt_madrid.config_flow.APIEMT._make_request",
        side_effect=make_request_mock,
    )
    async def test_user_flow_invalid_auth(self, mock_request, hass: HomeAssistant) -> None:
        """Test config flow with invalid credentials."""
        hass.states.async_set(
            "zone.home",
            "zoning",
            {"latitude": 40.4168, "longitude": -3.7038}
        )

        flow = self._init_flow(hass)

        result = await flow.async_step_user(
            user_input={
                CONF_EMAIL: "invalid@email.com",
                CONF_PASSWORD: "password123",
                CONF_RADIUS: 300,
                CONF_STOPS: "",
            }
        )

        assert result["type"].value == "form"
        assert result["errors"]["base"] == "invalid_auth"

    @patch(
        "custom_components.emt_madrid.config_flow.APIEMT._make_request",
        side_effect=make_request_mock,
    )
    async def test_user_flow_no_home_zone(self, mock_request, hass: HomeAssistant) -> None:
        """Test config flow without zone.home and no custom coordinates."""
        flow = self._init_flow(hass)

        result = await flow.async_step_user(
            user_input={
                CONF_EMAIL: "test@mail.com",
                CONF_PASSWORD: "password123",
                CONF_RADIUS: 300,
                CONF_STOPS: "",
            }
        )

        assert result["type"].value == "form"
        assert result["errors"]["base"] == "no_home_zone"

    @patch(
        "custom_components.emt_madrid.config_flow.APIEMT._make_request",
        side_effect=make_request_mock,
    )
    async def test_user_flow_with_custom_coordinates(self, mock_request, hass: HomeAssistant) -> None:
        """Test config flow with custom coordinates (no zone.home needed)."""
        flow = self._init_flow(hass)

        result = await flow.async_step_user(
            user_input={
                CONF_EMAIL: "test@mail.com",
                CONF_PASSWORD: "password123",
                CONF_RADIUS: 500,
                CONF_LATITUDE: 40.4168,
                CONF_LONGITUDE: -3.7038,
                CONF_STOPS: "72, 73",
            }
        )

        assert result["type"].value == "create_entry"
        assert result["data"][CONF_LATITUDE] == 40.4168
        assert result["data"][CONF_LONGITUDE] == -3.7038
        assert result["data"][CONF_STOPS] == [72, 73]

    async def test_user_flow_invalid_stops(self, hass: HomeAssistant) -> None:
        """Test config flow with invalid stop IDs."""
        hass.states.async_set(
            "zone.home",
            "zoning",
            {"latitude": 40.4168, "longitude": -3.7038}
        )

        flow = self._init_flow(hass)

        result = await flow.async_step_user(
            user_input={
                CONF_EMAIL: "test@mail.com",
                CONF_PASSWORD: "password123",
                CONF_RADIUS: 300,
                CONF_STOPS: "abc, 123",
            }
        )

        assert result["type"].value == "form"
        assert result["errors"]["base"] == "invalid_stops"


class TestAPIEMT:
    """Test the APIEMT class."""

    @patch(
        "custom_components.emt_madrid.emt_madrid.APIEMT._make_request",
        side_effect=make_request_mock,
    )
    def test_authenticate_success(self, mock_request) -> None:
        """Test successful authentication."""
        from custom_components.emt_madrid.emt_madrid import APIEMT

        api = APIEMT("test@mail.com", "password123", 0)
        api.authenticate()

        assert api._token == "3bd5855a-ed3d-41d5-8b4b-182726f86031"

    @patch(
        "custom_components.emt_madrid.emt_madrid.APIEMT._make_request",
        side_effect=make_request_mock,
    )
    def test_authenticate_failure(self, mock_request) -> None:
        """Test failed authentication."""
        from custom_components.emt_madrid.emt_madrid import APIEMT

        api = APIEMT("invalid@email.com", "password123", 0)
        api.authenticate()

        assert api._token == "Invalid token"

    @patch(
        "custom_components.emt_madrid.emt_madrid.APIEMT._make_request",
        side_effect=make_request_mock,
    )
    def test_get_stops_from_coordinates(self, mock_request) -> None:
        """Test getting stops from coordinates."""
        from custom_components.emt_madrid.emt_madrid import APIEMT

        api = APIEMT("test@mail.com", "password123", 0)
        api.authenticate()

        stops = api.get_stops_from_coordinates(-3.7038, 40.4168, 300)

        assert len(stops) == 2
        assert stops[0]["stop_id"] == "72"
        assert stops[0]["stop_name"] == "Cibeles-Casa de América"
        assert stops[0]["distance"] == 150
        assert "27" in stops[0]["lines"]

    @patch(
        "custom_components.emt_madrid.emt_madrid.APIEMT._make_request",
        side_effect=make_request_mock,
    )
    def test_get_nearby_arrivals(self, mock_request) -> None:
        """Test getting nearby arrivals."""
        from custom_components.emt_madrid.emt_madrid import APIEMT

        api = APIEMT("test@mail.com", "password123", 0)
        api.authenticate()

        arrivals = api.get_nearby_arrivals(-3.7038, 40.4168, 300, 10)

        assert len(arrivals) > 0
        # Arrivals should be sorted by minutes
        for i in range(len(arrivals) - 1):
            assert arrivals[i]["minutes"] <= arrivals[i + 1]["minutes"]
        # Check arrival structure
        assert "line" in arrivals[0]
        assert "minutes" in arrivals[0]
        assert "stop_name" in arrivals[0]

    @patch(
        "custom_components.emt_madrid.emt_madrid.APIEMT._make_request",
        side_effect=make_request_mock,
    )
    def test_get_nearby_arrivals_invalid_token(self, mock_request) -> None:
        """Test getting nearby arrivals with invalid token."""
        from custom_components.emt_madrid.emt_madrid import APIEMT

        api = APIEMT("invalid@email.com", "password123", 0)
        api.authenticate()

        arrivals = api.get_nearby_arrivals(-3.7038, 40.4168, 300, 10)

        assert arrivals == []


class TestSpeechFormatting:
    """Test the speech formatting function."""

    def test_format_empty_arrivals(self) -> None:
        """Test formatting empty arrivals."""
        from custom_components.emt_madrid import _format_arrivals_for_speech

        result = _format_arrivals_for_speech([])
        assert result == "No hay autobuses llegando a paradas cercanas en este momento."

    def test_format_single_arrival(self) -> None:
        """Test formatting single arrival."""
        from custom_components.emt_madrid import _format_arrivals_for_speech

        arrivals = [{"line": "27", "minutes": 3}]
        result = _format_arrivals_for_speech(arrivals)
        assert result == "Línea 27 en 3 minutos."

    def test_format_arrival_now(self) -> None:
        """Test formatting arrival arriving now."""
        from custom_components.emt_madrid import _format_arrivals_for_speech

        arrivals = [{"line": "27", "minutes": 0}]
        result = _format_arrivals_for_speech(arrivals)
        assert result == "Línea 27 llegando ahora."

    def test_format_arrival_one_minute(self) -> None:
        """Test formatting arrival in one minute."""
        from custom_components.emt_madrid import _format_arrivals_for_speech

        arrivals = [{"line": "27", "minutes": 1}]
        result = _format_arrivals_for_speech(arrivals)
        assert result == "Línea 27 en 1 minuto."

    def test_format_two_arrivals(self) -> None:
        """Test formatting two arrivals."""
        from custom_components.emt_madrid import _format_arrivals_for_speech

        arrivals = [{"line": "27", "minutes": 3}, {"line": "5", "minutes": 7}]
        result = _format_arrivals_for_speech(arrivals)
        assert result == "Línea 27 en 3 minutos y Línea 5 en 7 minutos."

    def test_format_multiple_arrivals(self) -> None:
        """Test formatting multiple arrivals."""
        from custom_components.emt_madrid import _format_arrivals_for_speech

        arrivals = [
            {"line": "27", "minutes": 3},
            {"line": "5", "minutes": 7},
            {"line": "14", "minutes": 12}
        ]
        result = _format_arrivals_for_speech(arrivals)
        assert result == "Línea 27 en 3 minutos, Línea 5 en 7 minutos, y Línea 14 en 12 minutos."

    def test_format_duplicate_lines(self) -> None:
        """Test that duplicate lines are not repeated."""
        from custom_components.emt_madrid import _format_arrivals_for_speech

        arrivals = [
            {"line": "27", "minutes": 3},
            {"line": "27", "minutes": 10},  # Same line, should be ignored
            {"line": "5", "minutes": 7}
        ]
        result = _format_arrivals_for_speech(arrivals)
        assert result == "Línea 27 en 3 minutos y Línea 5 en 7 minutos."
