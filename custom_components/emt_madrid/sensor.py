"""Support for EMT Madrid (Empresa Municipal de Transportes de Madrid) to get next departures."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_RADIUS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .emt_madrid import APIEMT

_LOGGER = logging.getLogger(__name__)

DOMAIN = "emt_madrid"
CONF_STOPS = "stops"

SCAN_INTERVAL = timedelta(minutes=1)

ATTR_ARRIVALS = "arrivals"
ATTR_STOPS_COUNT = "stops_count"
ATTR_SPEECH = "speech"
ATTR_RADIUS = "radius"
ATTR_EXTRA_STOPS = "extra_stops"
ATTR_LATITUDE = "latitude"
ATTR_LONGITUDE = "longitude"
ATTRIBUTION = "Data provided by EMT Madrid MobilityLabs"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EMT Madrid sensor from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    api: APIEMT = data["api"]
    config = data["config"]

    radius = config.get(CONF_RADIUS, 300)
    extra_stops = config.get(CONF_STOPS, [])
    custom_lat = config.get(CONF_LATITUDE)
    custom_lon = config.get(CONF_LONGITUDE)

    # Create the main nearby arrivals sensor
    sensors = [
        EMTNearbyArrivalsSensor(
            hass=hass,
            api=api,
            radius=radius,
            extra_stops=extra_stops,
            custom_latitude=custom_lat,
            custom_longitude=custom_lon,
            entry_id=entry.entry_id,
        )
    ]

    async_add_entities(sensors, True)


class EMTNearbyArrivalsSensor(SensorEntity):
    """Sensor showing next bus arrivals near configured location."""

    _attr_attribution = ATTRIBUTION
    _attr_icon = "mdi:bus-clock"
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        api: APIEMT,
        radius: int,
        extra_stops: list[int],
        custom_latitude: float | None,
        custom_longitude: float | None,
        entry_id: str,
    ) -> None:
        """Initialize the sensor."""
        self._hass = hass
        self._api = api
        self._radius = radius
        self._extra_stops = extra_stops
        self._custom_latitude = custom_latitude
        self._custom_longitude = custom_longitude
        self._attr_unique_id = f"emt_madrid_nearby_{entry_id}"
        self._attr_name = "EMT Nearby Buses"
        self._arrivals: list[dict] = []
        self._stops_count = 0
        self._current_lat: float | None = None
        self._current_lon: float | None = None

    @property
    def native_value(self) -> str | None:
        """Return the state - next bus info."""
        if self._arrivals:
            next_bus = self._arrivals[0]
            return f"{next_bus['line']} en {next_bus['minutes']} min"
        return "Sin buses"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the device state attributes."""
        return {
            ATTR_ARRIVALS: self._arrivals[:10],
            ATTR_STOPS_COUNT: self._stops_count,
            ATTR_SPEECH: self._format_speech(),
            ATTR_RADIUS: self._radius,
            ATTR_EXTRA_STOPS: self._extra_stops,
            ATTR_LATITUDE: self._current_lat,
            ATTR_LONGITUDE: self._current_lon,
        }

    def _format_speech(self) -> str:
        """Format arrivals for voice response."""
        if not self._arrivals:
            return "No hay autobuses llegando a paradas cercanas en este momento."

        lines_mentioned = set()
        speech_parts = []

        for arrival in self._arrivals[:5]:
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

    def _get_coordinates(self) -> tuple[float | None, float | None]:
        """Get coordinates from custom config or zone.home."""
        if self._custom_latitude is not None and self._custom_longitude is not None:
            return self._custom_latitude, self._custom_longitude

        zone_home = self._hass.states.get("zone.home")
        if zone_home:
            return (
                zone_home.attributes.get("latitude"),
                zone_home.attributes.get("longitude"),
            )

        return None, None

    async def async_update(self) -> None:
        """Fetch new state data for the sensor."""
        latitude, longitude = self._get_coordinates()

        if latitude is None or longitude is None:
            _LOGGER.warning("No coordinates available")
            return

        self._current_lat = latitude
        self._current_lon = longitude

        # Get nearby arrivals
        arrivals = await self._hass.async_add_executor_job(
            self._api.get_nearby_arrivals,
            longitude,
            latitude,
            self._radius,
            20,
        )

        # Also get arrivals from extra stops if configured
        if self._extra_stops:
            for stop_id in self._extra_stops:
                try:
                    await self._hass.async_add_executor_job(
                        self._api.update_stop_info, stop_id
                    )
                    await self._hass.async_add_executor_job(
                        self._api.update_arrival_times, stop_id
                    )
                    stop_info = self._api.get_stop_info()

                    for line, line_info in stop_info.get("lines", {}).items():
                        for i, arrival_time in enumerate(line_info.get("arrivals", [])):
                            if arrival_time is not None:
                                distances = line_info.get("distance", [])
                                arrivals.append({
                                    "stop_name": stop_info.get("bus_stop_name"),
                                    "stop_id": stop_id,
                                    "stop_distance": None,
                                    "line": line,
                                    "destination": line_info.get("destination"),
                                    "minutes": arrival_time,
                                    "bus_distance": distances[i] if i < len(distances) else None,
                                })
                except Exception as e:
                    _LOGGER.warning(f"Error getting arrivals for stop {stop_id}: {e}")

        # Sort all arrivals by time
        arrivals.sort(key=lambda x: x["minutes"])

        self._arrivals = arrivals
        self._stops_count = len(set(a.get("stop_id") for a in arrivals if a.get("stop_id")))
