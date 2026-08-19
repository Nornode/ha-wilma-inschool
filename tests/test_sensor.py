"""Test the Wilma sensor platform."""
from unittest.mock import AsyncMock, patch

from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import async_get as get_entity_registry

from custom_components.wilma.const import (
    ATTR_CONTENT,
    ATTR_CONTENT_MARKDOWN,
    ATTR_ID,
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