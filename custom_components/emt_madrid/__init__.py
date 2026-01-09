"""EMT Madrid integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_RADIUS, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .emt_madrid import APIEMT

_LOGGER = logging.getLogger(__name__)

DOMAIN = "emt_madrid"
CONF_STOP_ID = "stop_id"
CONF_STOPS = "stops"

PLATFORMS: list[Platform] = [Platform.SENSOR]

# Schema for YAML configuration (legacy support)
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_EMAIL): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Optional(CONF_STOP_ID): cv.positive_int,
                vol.Optional(CONF_STOPS): vol.All(cv.ensure_list, [cv.positive_int]),
                vol.Optional(CONF_RADIUS, default=300): vol.All(
                    vol.Coerce(int), vol.Range(min=50, max=1000)
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

SERVICE_NEARBY_ARRIVALS = "get_nearby_arrivals"
SERVICE_NEARBY_ARRIVALS_SCHEMA = vol.Schema({
    vol.Optional("latitude"): cv.latitude,
    vol.Optional("longitude"): cv.longitude,
    vol.Optional("radius", default=300): vol.All(vol.Coerce(int), vol.Range(min=50, max=1000)),
    vol.Optional("max_results", default=5): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the EMT Madrid component."""
    hass.data.setdefault(DOMAIN, {})

    # Check for YAML configuration and import it
    if DOMAIN in config:
        yaml_config = config[DOMAIN]

        # Check if already imported
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.source == SOURCE_IMPORT:
                _LOGGER.debug("EMT Madrid already imported from YAML")
                return True

        _LOGGER.info("Importing EMT Madrid configuration from YAML")

        # Build stops list from old config
        stops = yaml_config.get(CONF_STOPS, [])
        if yaml_config.get(CONF_STOP_ID):
            stops.append(yaml_config[CONF_STOP_ID])

        # Create config entry from YAML
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data={
                    CONF_EMAIL: yaml_config[CONF_EMAIL],
                    CONF_PASSWORD: yaml_config[CONF_PASSWORD],
                    CONF_RADIUS: yaml_config.get(CONF_RADIUS, 300),
                    CONF_STOPS: stops,
                },
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up EMT Madrid from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Create API instance
    api = APIEMT(
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
        0  # No fixed stop - dynamic
    )

    # Authenticate
    await hass.async_add_executor_job(api.authenticate)

    if api._token == "Invalid token":
        _LOGGER.error("Failed to authenticate with EMT Madrid API")
        return False

    # Store API instance and config
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "config": entry.data,
    }

    # Store credentials for service use
    hass.data[DOMAIN]["credentials"] = {
        "email": entry.data[CONF_EMAIL],
        "password": entry.data[CONF_PASSWORD],
    }
    hass.data[DOMAIN]["radius"] = entry.data.get(CONF_RADIUS, 300)

    # Register service (only once)
    if not hass.services.has_service(DOMAIN, SERVICE_NEARBY_ARRIVALS):
        await _async_register_services(hass)

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def _async_register_services(hass: HomeAssistant) -> None:
    """Register EMT Madrid services."""

    async def handle_nearby_arrivals(call: ServiceCall) -> ServiceResponse:
        """Handle the nearby arrivals service call."""
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

        radius = call.data.get("radius", hass.data[DOMAIN].get("radius", 300))
        max_results = call.data.get("max_results", 5)

        # Get API instance
        if DOMAIN in hass.data and "credentials" in hass.data[DOMAIN]:
            creds = hass.data[DOMAIN]["credentials"]
            api = APIEMT(creds["email"], creds["password"], 0)
            await hass.async_add_executor_job(api.authenticate)
        else:
            return {
                "error": "No EMT Madrid credentials configured.",
                "arrivals": [],
                "speech": "No hay credenciales de EMT Madrid configuradas.",
                "count": 0
            }

        # Get nearby arrivals
        arrivals = await hass.async_add_executor_job(
            api.get_nearby_arrivals, longitude, latitude, radius, max_results
        )

        # Format for voice response
        speech_text = _format_arrivals_for_speech(arrivals)

        return {
            "arrivals": arrivals,
            "speech": speech_text,
            "count": len(arrivals)
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_NEARBY_ARRIVALS,
        handle_nearby_arrivals,
        schema=SERVICE_NEARBY_ARRIVALS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )


def _format_arrivals_for_speech(arrivals: list) -> str:
    """Format arrivals list into a voice-friendly string in Spanish."""
    if not arrivals:
        return "No hay autobuses llegando a paradas cercanas en este momento."

    lines_mentioned = set()
    speech_parts = []

    for arrival in arrivals:
        line = arrival["line"]
        minutes = arrival["minutes"]
        stop_name = arrival.get("stop_name", "")

        if line not in lines_mentioned:
            if minutes == 0:
                if stop_name:
                    speech_parts.append(f"Línea {line} llegando ahora en {stop_name}")
                else:
                    speech_parts.append(f"Línea {line} llegando ahora")
            elif minutes == 1:
                if stop_name:
                    speech_parts.append(f"Línea {line} en 1 minuto en {stop_name}")
                else:
                    speech_parts.append(f"Línea {line} en 1 minuto")
            else:
                if stop_name:
                    speech_parts.append(f"Línea {line} en {minutes} minutos en {stop_name}")
                else:
                    speech_parts.append(f"Línea {line} en {minutes} minutos")
            lines_mentioned.add(line)

    if len(speech_parts) == 1:
        return speech_parts[0] + "."
    elif len(speech_parts) == 2:
        return f"{speech_parts[0]} y {speech_parts[1]}."
    else:
        return ", ".join(speech_parts[:-1]) + f", y {speech_parts[-1]}."
