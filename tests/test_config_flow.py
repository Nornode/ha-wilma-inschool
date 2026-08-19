"""Test the Wilma config flow."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries, data_entry_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wilma.const import (
    CONF_PASSWORD,
    CONF_SERVER_URL,
    CONF_USERNAME,
    DOMAIN,
)


async def test_form(hass, mock_wilma_flow_client):
    """Test we get the form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {}

    # Test form submission
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SERVER_URL: "https://test.inschool.fi",
            CONF_USERNAME: "testuser",
            CONF_PASSWORD: "testpass",
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Wilma (testuser)"
    assert result["data"] == {
        CONF_SERVER_URL: "https://test.inschool.fi",
        CONF_USERNAME: "testuser",
        CONF_PASSWORD: "testpass",
    }


async def test_form_invalid_auth(hass, mock_wilma_exception_client):
    """Test we handle invalid auth."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SERVER_URL: "https://test.inschool.fi",
            CONF_USERNAME: "testuser",
            CONF_PASSWORD: "testpass",
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_form_auth_rejected(hass):
    """Test token 403 is surfaced as server auth rejection, not bad credentials."""
    from wilhelmina import AuthenticationError

    client = MagicMock()
    client.login = AsyncMock(side_effect=AuthenticationError("Failed to get token: 403"))
    client.get_messages = AsyncMock(return_value=[])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("custom_components.wilma.config_flow.WilmaClient", return_value=client):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_SERVER_URL: "https://test.inschool.fi",
                CONF_USERNAME: "testuser",
                CONF_PASSWORD: "testpass",
            },
        )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "auth_rejected"}


async def test_duplicate_entries(hass, mock_wilma_flow_client):
    """Test handling of duplicate entries."""
    # Add existing entry
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SERVER_URL: "https://test.inschool.fi",
            CONF_USERNAME: "testuser",
            CONF_PASSWORD: "testpass",
        },
        unique_id="testuser@test.inschool.fi",
    )
    entry.add_to_hass(hass)

    # Initialize flow
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Submit same data
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SERVER_URL: "https://test.inschool.fi",
            CONF_USERNAME: "testuser",
            CONF_PASSWORD: "testpass",
        },
    )

    # Should still allow creating, as we don't set unique_id in the integration yet
    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY


async def test_options_flow(hass, mock_config_entry):
    """Test options flow fields and save."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] == data_entry_flow.FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "scan_interval_minutes": 10,
            "only_unread": True,
            "no_message_content_fetch_limit": True,
        },
    )

    assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["data"]["scan_interval_minutes"] == 10
    assert result["data"]["only_unread"] is True
    assert result["data"]["no_message_content_fetch_limit"] is True