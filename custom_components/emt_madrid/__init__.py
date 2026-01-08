"""EMT Madrid integration."""

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .emt_madrid import APIEMT

_LOGGER = logging.getLogger(__name__)

DOMAIN = "emt_madrid"

SERVICE_NEARBY_ARRIVALS = "get_nearby_arrivals"
SERVICE_NEARBY_ARRIVALS_SCHEMA = vol.Schema({
    vol.Optional("latitude"): cv.latitude,
    vol.Optional("longitude"): cv.longitude,
    vol.Optional("radius", default=300): vol.All(vol.Coerce(int), vol.Range(min=50, max=1000)),
    vol.Optional("max_results", default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
})

_api_instance: APIEMT | None = None


def setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the EMT Madrid component."""

    def handle_nearby_arrivals(call: ServiceCall) -> ServiceResponse:
        """Handle the nearby arrivals service call."""
        global _api_instance

        # Get coordinates from call or from zone.home
        latitude = call.data.get("latitude")
        longitude = call.data.get("longitude")

        if latitude is None or longitude is None:
            zone_home = hass.states.get("zone.home")
            if zone_home:
                latitude = zone_home.attributes.get("latitude")
                longitude = zone_home.attributes.get("longitude")
            else:
                return {
                    "error": "No coordinates provided and zone.home not found",
                    "arrivals": [],
                    "speech": "No se pudo determinar la ubicación del hogar.",
                    "count": 0
                }

        radius = call.data.get("radius", 300)
        max_results = call.data.get("max_results", 5)

        # Get API instance from hass.data (set by sensor platform)
        if _api_instance is None:
            if DOMAIN in hass.data and "credentials" in hass.data[DOMAIN]:
                creds = hass.data[DOMAIN]["credentials"]
                _api_instance = APIEMT(creds["email"], creds["password"], 0)
                _api_instance.authenticate()
            else:
                return {
                    "error": "No EMT Madrid credentials configured. Add an emt_madrid sensor first.",
                    "arrivals": [],
                    "speech": "No hay credenciales de EMT Madrid configuradas.",
                    "count": 0
                }

        # Get nearby arrivals
        arrivals = _api_instance.get_nearby_arrivals(longitude, latitude, radius, max_results)

        # Format for voice response
        speech_text = _format_arrivals_for_speech(arrivals)

        return {
            "arrivals": arrivals,
            "speech": speech_text,
            "count": len(arrivals)
        }

    hass.services.register(
        DOMAIN,
        SERVICE_NEARBY_ARRIVALS,
        handle_nearby_arrivals,
        schema=SERVICE_NEARBY_ARRIVALS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    return True


def _format_arrivals_for_speech(arrivals: list) -> str:
    """Format arrivals list into a voice-friendly string in Spanish."""
    if not arrivals:
        return "No hay autobuses llegando a paradas cercanas en este momento."

    # Group by line to avoid repetition
    lines_mentioned = set()
    speech_parts = []

    for arrival in arrivals:
        line = arrival["line"]
        minutes = arrival["minutes"]

        if line not in lines_mentioned:
            if minutes == 0:
                speech_parts.append(f"Línea {line} llegando ahora")
            elif minutes == 1:
                speech_parts.append(f"Línea {line} en 1 minuto")
            else:
                speech_parts.append(f"Línea {line} en {minutes} minutos")
            lines_mentioned.add(line)

    if len(speech_parts) == 1:
        return speech_parts[0] + "."
    elif len(speech_parts) == 2:
        return f"{speech_parts[0]} y {speech_parts[1]}."
    else:
        return ", ".join(speech_parts[:-1]) + f", y {speech_parts[-1]}."
