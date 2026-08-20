"""Test the Wilma sensor platform."""
from unittest.mock import AsyncMock, patch

from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import async_get as get_entity_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wilma.const import (
    ATTR_CONTENT,
    ATTR_CONTENT_MARKDOWN,
    ATTR_ID,
    ATTR_NEWS_ID,
    CONF_LANGUAGE,
    ATTR_SENDER,
    ATTR_STUDENT_ID,
    ATTR_STUDENT_NAME,
    ATTR_SUBJECT,
    ATTR_TIMESTAMP,
    DOMAIN,
)


def _entity_id_for_unique_id(hass: HomeAssistant, unique_id: str) -> str:
    registry = get_entity_registry(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id is not None
    return entity_id


def _entity_id_for_unique_id_with_domain(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    registry = get_entity_registry(hass)
    entity_id = registry.async_get_entity_id(domain, DOMAIN, unique_id)
    assert entity_id is not None
    return entity_id


async def test_sensors_state(hass: HomeAssistant, mock_setup_integration):
    """Test sensor states."""
    # Complete setup
    await mock_setup_integration()

    # Check student 1 latest message sensor
    state = hass.states.get(
        _entity_id_for_unique_id(hass, "test_!STUDENT1_latest_message")
    )
    assert state is not None
    assert state.state == "Test Message 1"

    # Check attributes
    assert state.attributes[ATTR_ID] == 1
    assert state.attributes[ATTR_SUBJECT] == "Test Message 1"
    assert state.attributes[ATTR_SENDER] == "Sender 1"
    assert state.attributes[ATTR_TIMESTAMP] == "2023-01-02 12:00"
    assert state.attributes[ATTR_STUDENT_ID] == "!STUDENT1"
    assert state.attributes[ATTR_STUDENT_NAME] == "Kid One"
    assert ATTR_CONTENT in state.attributes
    assert ATTR_CONTENT_MARKDOWN in state.attributes

    # Check student 1 unread count sensor
    state = hass.states.get(
        _entity_id_for_unique_id(hass, "test_!STUDENT1_unread_count")
    )
    assert state is not None
    assert state.state == "1"

    # Check student 1 latest bulletin sensor
    state = hass.states.get(
        _entity_id_for_unique_id(hass, "test_!STUDENT1_latest_bulletin")
    )
    assert state is not None
    assert state.state == "Kid One latest bulletin"
    assert state.attributes[ATTR_NEWS_ID] == 101
    assert ATTR_CONTENT not in state.attributes
    assert "Line one for kid one." in state.attributes[ATTR_CONTENT_MARKDOWN]
    assert "[link](https://example.com)" in state.attributes[ATTR_CONTENT_MARKDOWN]

    # Check student 1 unread bulletin count sensor
    state = hass.states.get(
        _entity_id_for_unique_id(hass, "test_!STUDENT1_unread_bulletin_count")
    )
    assert state is not None
    assert state.state == "2"

    # Check student 2 latest message sensor
    state = hass.states.get(
        _entity_id_for_unique_id(hass, "test_!STUDENT2_latest_message")
    )
    assert state is not None
    assert state.state == "Test Message 11"

    # Check student 2 unread count sensor
    state = hass.states.get(
        _entity_id_for_unique_id(hass, "test_!STUDENT2_unread_count")
    )
    assert state is not None
    assert state.state == "1"

    # Check one diagnostic sensor
    state = hass.states.get(
        _entity_id_for_unique_id(hass, "test_!STUDENT1_last_update")
    )
    assert state is not None
    assert state.state != STATE_UNKNOWN


async def test_sensor_no_messages(hass: HomeAssistant, mock_config_entry):
    """Test sensor behavior when there are no messages."""
    # Set up empty messages return
    with patch("custom_components.wilma.coordinator.WilmaClient") as mock_client:
        client = mock_client.return_value
        client.user_id = "!STUDENT1"
        client._sid = "sid"
        client.base_url = "https://test.inschool.fi"
        client.login = AsyncMock()
        client.get_messages = AsyncMock(return_value=[])
        client._ensure_session = AsyncMock(side_effect=RuntimeError("No session"))

        # Set up entry
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Check latest message sensor - should be unknown
    state = hass.states.get(
        _entity_id_for_unique_id(hass, "test_!STUDENT1_latest_message")
    )
    assert state is not None
    assert state.state == STATE_UNKNOWN

    # Check unread messages sensor for no messages
    state = hass.states.get(
        _entity_id_for_unique_id(hass, "test_!STUDENT1_unread_count")
    )
    assert state is not None
    assert state.state == "0"


async def test_sensor_friendly_names_follow_integration_language(
    hass: HomeAssistant,
    mock_wilma_client,
):
    """Test that entity friendly names follow the Wilma language option, not HA language."""
    mock_config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "server_url": "https://test.inschool.fi",
            "username": "testuser",
            "password": "testpass",
        },
        options={CONF_LANGUAGE: "2"},
        entry_id="test-sv",
    )
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(
        _entity_id_for_unique_id(hass, "test-sv_!STUDENT1_unread_count")
    )
    assert state is not None
    assert state.name is not None
    assert "Unread" not in state.name
    assert "Olästa" in state.name
    assert "meddelanden" in state.name

    registry = get_entity_registry(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, "test-sv_!STUDENT1_unread_count"
    )
    assert entity_id is not None
    assert entity_id.startswith("sensor.wilma_kid_")
    assert entity_id.endswith("unread_count")
    assert "meddelanden" not in entity_id
    assert "notiser" not in entity_id

    recent_attendance_entity_id = _entity_id_for_unique_id_with_domain(
        hass,
        "binary_sensor",
        "test-sv_!STUDENT1_recent_attendance",
    )
    recent_attendance_state = hass.states.get(recent_attendance_entity_id)
    assert recent_attendance_state is not None
    assert recent_attendance_state.name is not None
    assert "recent_attendance" not in recent_attendance_state.name.lower()
    assert (
        "lektionsanteckning" in recent_attendance_state.name.lower()
        or "tuntimerk" in recent_attendance_state.name.lower()
    )

    # Check unread bulletin sensor for no news
    state = hass.states.get(
        _entity_id_for_unique_id(hass, "test-sv_!STUDENT1_unread_bulletin_count")
    )
    assert state is not None
    assert state.state == "2"
