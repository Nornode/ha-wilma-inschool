"""Test the Wilma integration initialization."""
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import (
    RegistryEntryDisabler,
    async_get as get_entity_registry,
)

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
    for summary_key in (
        "latest_message_summary_part_1",
        "latest_bulletin_summary_part_1",
        "latest_attendance_summary_part_1",
    ):
        text_entity_id = entity_registry.async_get_entity_id(
            "text", DOMAIN, f"test_!STUDENT1_{summary_key}"
        )
        assert text_entity_id is not None
        text_entry = entity_registry.async_get(text_entity_id)
        assert text_entry is not None
        assert text_entry.disabled_by is RegistryEntryDisabler.INTEGRATION

    # Unload the entry
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    # Verify coordinator is removed from hass.data
    assert entry.entry_id not in hass.data[DOMAIN]


async def test_setup_clears_generated_entity_names(hass: HomeAssistant, mock_setup_integration):
    """Test that previously generated entity names do not block translated names."""
    entry = await mock_setup_integration()
    entity_registry = get_entity_registry(hass)

    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, "test_!STUDENT1_unread_count"
    )
    assert entity_id is not None

    entity_registry.async_update_entity(entity_id, name="Unread Notiser")
    assert entity_registry.async_get(entity_id).name == "Unread Notiser"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    mock_config_entry = await mock_setup_integration()
    await hass.async_block_till_done()

    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, "test_!STUDENT1_unread_count"
    )
    assert entity_id is not None
    assert entity_registry.async_get(entity_id).name is None

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_long_summary_is_exposed_in_attribute(
    hass: HomeAssistant, mock_setup_integration
):
    """Test that concatenated summary text is available in part-1 attributes."""
    entry = await mock_setup_integration()
    entity_registry = get_entity_registry(hass)

    summary_keys = [
        "latest_message_summary_part_1",
        "latest_message_summary_part_2",
        "latest_message_summary_part_3",
    ]
    for summary_key in summary_keys:
        entity_id = entity_registry.async_get_entity_id(
            "text", DOMAIN, f"test_!STUDENT1_{summary_key}"
        )
        assert entity_id is not None
        entity_registry.async_update_entity(entity_id, disabled_by=None)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    part_1 = entity_registry.async_get_entity_id(
        "text", DOMAIN, "test_!STUDENT1_latest_message_summary_part_1"
    )
    part_2 = entity_registry.async_get_entity_id(
        "text", DOMAIN, "test_!STUDENT1_latest_message_summary_part_2"
    )
    part_3 = entity_registry.async_get_entity_id(
        "text", DOMAIN, "test_!STUDENT1_latest_message_summary_part_3"
    )
    assert part_1 is not None
    assert part_2 is not None
    assert part_3 is not None

    long_summary = "A" * 255 + "B" * 255 + "C" * 120

    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": part_1, "value": long_summary[0:255]},
        blocking=True,
    )
    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": part_2, "value": long_summary[255:510]},
        blocking=True,
    )
    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": part_3, "value": long_summary[510:765]},
        blocking=True,
    )

    await hass.services.async_call(
        "homeassistant",
        "update_entity",
        {"entity_id": part_1},
        blocking=True,
    )

    state = hass.states.get(part_1)
    assert state is not None
    assert state.state == long_summary[0:255]
    assert state.attributes.get("summary") == long_summary
    assert state.attributes.get("summary_length") == len(long_summary)
