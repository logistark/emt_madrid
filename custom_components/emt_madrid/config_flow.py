"""Config flow for EMT Madrid integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow, ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_RADIUS, CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .emt_madrid import APIEMT

_LOGGER = logging.getLogger(__name__)

DOMAIN = "emt_madrid"
CONF_STOPS = "stops"

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_RADIUS, default=300): vol.All(
            vol.Coerce(int), vol.Range(min=50, max=1000)
        ),
        vol.Optional(CONF_LATITUDE): vol.Coerce(float),
        vol.Optional(CONF_LONGITUDE): vol.Coerce(float),
        vol.Optional(CONF_STOPS, default=""): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    api = APIEMT(data[CONF_EMAIL], data[CONF_PASSWORD], 0)

    # Run blocking calls in executor
    await hass.async_add_executor_job(api.authenticate)

    if api._token == "Invalid token":
        raise InvalidAuth

    # Check if we have coordinates (custom or from zone.home)
    has_custom_coords = data.get(CONF_LATITUDE) is not None and data.get(CONF_LONGITUDE) is not None

    if not has_custom_coords:
        zone_home = hass.states.get("zone.home")
        if not zone_home:
            raise NoHomeZone

    return {"title": "EMT Madrid"}


class EMTMadridConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EMT Madrid."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return EMTMadridOptionsFlow()

    async def async_step_import(
        self, import_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle import from YAML configuration."""
        # Check if already configured
        await self.async_set_unique_id("emt_madrid_nearby")
        self._abort_if_unique_id_configured()

        # Validate credentials
        try:
            await validate_input(self.hass, import_data)
        except InvalidAuth:
            _LOGGER.error("Invalid EMT Madrid credentials in YAML configuration")
            return self.async_abort(reason="invalid_auth")
        except NoHomeZone:
            _LOGGER.error("No home zone configured for EMT Madrid")
            return self.async_abort(reason="no_home_zone")
        except Exception:
            _LOGGER.exception("Error importing EMT Madrid configuration")
            return self.async_abort(reason="unknown")

        _LOGGER.info("Successfully imported EMT Madrid from YAML. You can now remove the YAML configuration.")

        return self.async_create_entry(
            title="EMT Madrid",
            data=import_data,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Parse stops from comma-separated string
            stops_str = user_input.get(CONF_STOPS, "")
            stops = []
            for s in stops_str.split(","):
                s = s.strip()
                if s:
                    try:
                        stops.append(int(s))
                    except ValueError:
                        errors["base"] = "invalid_stops"
                        break

            if not errors:
                try:
                    info = await validate_input(self.hass, user_input)
                except InvalidAuth:
                    errors["base"] = "invalid_auth"
                except NoHomeZone:
                    errors["base"] = "no_home_zone"
                except Exception:
                    _LOGGER.exception("Unexpected exception")
                    errors["base"] = "unknown"
                else:
                    # Check if already configured
                    await self.async_set_unique_id("emt_madrid_nearby")
                    self._abort_if_unique_id_configured()

                    # Store data with parsed stops
                    data = {
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_RADIUS: user_input.get(CONF_RADIUS, 300),
                        CONF_STOPS: stops,
                    }

                    # Add custom coordinates if provided
                    if user_input.get(CONF_LATITUDE) is not None:
                        data[CONF_LATITUDE] = user_input[CONF_LATITUDE]
                    if user_input.get(CONF_LONGITUDE) is not None:
                        data[CONF_LONGITUDE] = user_input[CONF_LONGITUDE]

                    return self.async_create_entry(title=info["title"], data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )


class EMTMadridOptionsFlow(OptionsFlow):
    """Handle options flow for EMT Madrid."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Parse stops from comma-separated string
            stops_str = user_input.get(CONF_STOPS, "")
            stops = []
            if stops_str:
                for s in stops_str.split(","):
                    s = s.strip()
                    if s:
                        try:
                            stops.append(int(s))
                        except ValueError:
                            errors["base"] = "invalid_stops"
                            break

            if not errors:
                # Build new data, keeping email/password from original config
                new_data = {
                    CONF_EMAIL: self.config_entry.data[CONF_EMAIL],
                    CONF_PASSWORD: self.config_entry.data[CONF_PASSWORD],
                    CONF_RADIUS: user_input.get(CONF_RADIUS, 300),
                    CONF_STOPS: stops,
                }

                # Add custom coordinates if provided
                if user_input.get(CONF_LATITUDE) is not None:
                    new_data[CONF_LATITUDE] = user_input[CONF_LATITUDE]
                if user_input.get(CONF_LONGITUDE) is not None:
                    new_data[CONF_LONGITUDE] = user_input[CONF_LONGITUDE]

                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )
                return self.async_create_entry(title="", data={})

        # Get current values for defaults
        current_radius = self.config_entry.data.get(CONF_RADIUS, 300)
        current_lat = self.config_entry.data.get(CONF_LATITUDE)
        current_lon = self.config_entry.data.get(CONF_LONGITUDE)
        current_stops = self.config_entry.data.get(CONF_STOPS, [])
        stops_str = ", ".join(str(s) for s in current_stops) if current_stops else ""

        options_schema = vol.Schema(
            {
                vol.Optional(CONF_RADIUS, default=current_radius): vol.All(
                    vol.Coerce(int), vol.Range(min=50, max=1000)
                ),
                vol.Optional(CONF_LATITUDE, default=current_lat): vol.Any(None, vol.Coerce(float)),
                vol.Optional(CONF_LONGITUDE, default=current_lon): vol.Any(None, vol.Coerce(float)),
                vol.Optional(CONF_STOPS, default=stops_str): str,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
        )


class InvalidAuth(HomeAssistantError):
    """Error to indicate invalid authentication."""


class NoHomeZone(HomeAssistantError):
    """Error to indicate zone.home is not configured."""
