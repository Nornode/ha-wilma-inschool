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


async def test_setup_preserves_user_customized_entity_names(hass: HomeAssistant, mock_setup_integration):
    """Test that user customized entity names are preserved on reload/restart."""
    entry = await mock_setup_integration()
    entity_registry = get_entity_registry(hass)

    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, "test_!STUDENT1_unread_count"
    )
    assert entity_id is not None

    entity_registry.async_update_entity(entity_id, name="Next lesson Anna")
    assert entity_registry.async_get(entity_id).name == "Next lesson Anna"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, "test_!STUDENT1_unread_count"
    )
    assert entity_id is not None
    assert entity_registry.async_get(entity_id).name == "Next lesson Anna"


async def test_migration_v1_to_v2(hass: HomeAssistant, mock_wilma_client):
    """Test that migrating from version 1 to 2 clears stale prefixes and updates version."""
    from custom_components.wilma import async_migrate_entry
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry_v1 = MockConfigEntry(
        domain=DOMAIN,
        data={
            "server_url": "https://test.inschool.fi",
            "username": "testuser",
            "password": "testpass",
        },
        entry_id="test_mig",
        version=1,
    )
    entry_v1.add_to_hass(hass)

    entity_registry = get_entity_registry(hass)
    entity_entry = entity_registry.async_get_or_create(
        "sensor",
        DOMAIN,
        "test_mig_!STUDENT1_unread_count",
        suggested_object_id="test_mig_!STUDENT1_unread_count",
        config_entry=entry_v1,
    )
    entity_registry.async_update_entity(entity_entry.entity_id, name="Unread Messages")
    assert entity_registry.async_get(entity_entry.entity_id).name == "Unread Messages"

    # Run migration
    assert await async_migrate_entry(hass, entry_v1)
    assert entry_v1.version == 2
    assert entity_registry.async_get(entity_entry.entity_id).name is None


async def test_refresh_service(hass: HomeAssistant, mock_setup_integration):
    """Test calling wilma.refresh service triggers coordinator refresh."""
    from unittest.mock import AsyncMock, patch
    entry = await mock_setup_integration()
    coordinator = hass.data[DOMAIN][entry.entry_id]

    with patch.object(coordinator, "async_request_refresh", AsyncMock()) as mock_refresh:
        # Test refresh without target
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
        mock_refresh.assert_called_once()

    with patch.object(coordinator, "async_request_refresh", AsyncMock()) as mock_refresh:
        # Test refresh with explicit entry_id
        await hass.services.async_call(DOMAIN, "refresh", {"entry_id": entry.entry_id}, blocking=True)
        mock_refresh.assert_called_once()

    with patch.object(coordinator, "async_request_refresh", AsyncMock()) as mock_refresh:
        # Test refresh with target entity_id
        entity_reg = get_entity_registry(hass)
        entity_id = entity_reg.async_get_entity_id("sensor", DOMAIN, "test_!STUDENT1_latest_message")
        await hass.services.async_call(DOMAIN, "refresh", {"entity_id": [entity_id]}, blocking=True)
        mock_refresh.assert_called_once()


async def test_calendar_events_with_timezone(hass: HomeAssistant, mock_setup_integration):
    """Test calendar entity returns formatted events using dt_util timezone."""
    from datetime import datetime
    from homeassistant.util import dt as dt_util

    entry = await mock_setup_integration()
    coordinator = hass.data[DOMAIN][entry.entry_id]

    raw_event = {
        "id": "event_1",
        "date": "20.10.2099",
        "start_minutes": 540,
        "end_minutes": 600,
        "subject": "Matematik",
        "room": "Sal 101",
        "teachers": ["Lärare 1"],
    }
    coordinator.data["schedules"] = {"!STUDENT1": [raw_event]}

    entity_reg = get_entity_registry(hass)
    calendar_entity_id = entity_reg.async_get_entity_id("calendar", DOMAIN, "test_!STUDENT1_calendar")
    assert calendar_entity_id is not None

    entity = hass.data["entity_components"]["calendar"].get_entity(calendar_entity_id)
    assert entity is not None

    from unittest.mock import AsyncMock, patch
    with patch.object(
        coordinator,
        "async_fetch_schedule_for_student_range",
        AsyncMock(return_value=[raw_event]),
    ):
        events = await entity.async_get_events(
            hass,
            datetime(2099, 10, 20, 0, 0, tzinfo=dt_util.UTC),
            datetime(2099, 10, 20, 23, 59, tzinfo=dt_util.UTC),
        )
        assert len(events) == 1
        assert events[0].summary == "Matematik"
        assert events[0].location == "Sal 101"

    assert entity.event is not None
    assert entity.event.summary == "Matematik"
