"""Test the Wilma integration initialization."""
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import async_get as get_entity_registry

from custom_components.wilma.const import DOMAIN


async def test_setup_and_unload_entry(hass: HomeAssistant, mock_setup_integration):
    """Test setting up and unloading the integration."""
    entry = await mock_setup_integration()

    # Verify entry has been set up properly
    assert DOMAIN in hass.data
    assert entry.entry_id in hass.data[DOMAIN]
    
    # Verify entities are set up
    entity_registry = get_entity_registry(hass)
    assert (
        entity_registry.async_get_entity_id(
            "sensor", DOMAIN, "test_!STUDENT1_latest_message"
        )
        is not None
    )
    assert (
        entity_registry.async_get_entity_id(
            "sensor", DOMAIN, "test_!STUDENT1_unread_count"
        )
        is not None
    )
    assert (
        entity_registry.async_get_entity_id(
            "sensor", DOMAIN, "test_!STUDENT1_last_update"
        )
        is not None
    )
    assert (
        entity_registry.async_get_entity_id(
            "sensor", DOMAIN, "test_!STUDENT2_latest_message"
        )
        is not None
    )
    assert (
        entity_registry.async_get_entity_id(
            "sensor", DOMAIN, "test_!STUDENT2_last_update"
        )
        is not None
    )

    # Unload the entry
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    
    # Verify coordinator is removed from hass.data
    assert entry.entry_id not in hass.data[DOMAIN]