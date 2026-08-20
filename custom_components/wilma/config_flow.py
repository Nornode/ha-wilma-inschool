"""Config flow for Wilma integration."""

import logging
from typing import Any, Dict, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from wilhelmina import AuthenticationError, WilmaClient, WilmaError

from .const import (
    CONF_LANGUAGE,
    CONF_NO_MESSAGE_CONTENT_FETCH_LIMIT,
    CONF_ONLY_UNREAD,
    CONF_PASSWORD,
    CONF_RECENT_THRESHOLD_HOURS,
    CONF_SCAN_INTERVAL_MINUTES,
    CONF_SERVER_URL,
    CONF_USERNAME,
    DEFAULT_LANGUAGE,
    DEFAULT_NO_MESSAGE_CONTENT_FETCH_LIMIT,
    DEFAULT_ONLY_UNREAD,
    DEFAULT_RECENT_THRESHOLD_HOURS,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _is_server_auth_rejection(err: AuthenticationError) -> bool:
    """Return true when Wilma rejects token minting with HTTP 403."""
    err_text = str(err).lower()
    return "403" in err_text and "token" in err_text

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SERVER_URL): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_LANGUAGE, default=DEFAULT_LANGUAGE): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {"value": "1", "label": "Finnish (Suomi)"},
                    {"value": "2", "label": "Swedish (Svenska)"},
                    {"value": "3", "label": "English"},
                ],
            )
        ),
    }
)


async def validate_input(hass: HomeAssistant, data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    try:
        async with WilmaClient(data[CONF_SERVER_URL]) as client:
            await client.login(data[CONF_USERNAME], data[CONF_PASSWORD])

            # Test fetching messages
            messages = await client.get_messages()
            _LOGGER.debug(f"Successfully fetched {len(messages)} messages from Wilma")

    except AuthenticationError as err:
        if _is_server_auth_rejection(err):
            _LOGGER.error(
                "Wilma rejected token creation (HTTP 403). Credentials may be valid but login flow was rejected: %s",
                err,
            )
            raise AuthRejected from err

        _LOGGER.error("Authentication to Wilma failed: %s", err)
        raise InvalidAuth from err
    except WilmaError as err:
        _LOGGER.error("Error communicating with Wilma: %s", err)
        raise CannotConnect from err
    except Exception as err:
        _LOGGER.exception("Unexpected error validating Wilma connection: %s", err)
        raise CannotConnect from err

    # If we get here, connection is successful
    return {"title": f"Wilma ({data[CONF_USERNAME]})"}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Wilma."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return WilmaOptionsFlow()

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                entry_data = {
                    CONF_SERVER_URL: user_input[CONF_SERVER_URL],
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                entry_options = {CONF_LANGUAGE: user_input[CONF_LANGUAGE]}
                return self.async_create_entry(
                    title=info["title"],
                    data=entry_data,
                    options=entry_options,
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except AuthRejected:
                errors["base"] = "auth_rejected"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class AuthRejected(HomeAssistantError):
    """Error to indicate Wilma rejected token authentication."""


class WilmaOptionsFlow(config_entries.OptionsFlow):
    """Handle Wilma options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manage the integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL_MINUTES,
                    default=options.get(
                        CONF_SCAN_INTERVAL_MINUTES,
                        DEFAULT_SCAN_INTERVAL_MINUTES,
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=360)),
                vol.Optional(
                    CONF_ONLY_UNREAD,
                    default=options.get(CONF_ONLY_UNREAD, DEFAULT_ONLY_UNREAD),
                ): bool,
                vol.Optional(
                    CONF_NO_MESSAGE_CONTENT_FETCH_LIMIT,
                    default=options.get(
                        CONF_NO_MESSAGE_CONTENT_FETCH_LIMIT,
                        DEFAULT_NO_MESSAGE_CONTENT_FETCH_LIMIT,
                    ),
                ): bool,
                vol.Optional(
                    CONF_RECENT_THRESHOLD_HOURS,
                    default=options.get(CONF_RECENT_THRESHOLD_HOURS, DEFAULT_RECENT_THRESHOLD_HOURS),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=168)),
                vol.Optional(
                    CONF_LANGUAGE,
                    default=options.get(CONF_LANGUAGE, DEFAULT_LANGUAGE),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "1", "label": "Finnish (Suomi)"},
                            {"value": "2", "label": "Swedish (Svenska)"},
                            {"value": "3", "label": "English"},
                        ],
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
