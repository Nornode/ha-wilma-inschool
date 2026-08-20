"""The Wilma integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry

from .const import CONF_PASSWORD, CONF_SERVER_URL, CONF_USERNAME, DOMAIN
from .coordinator import WilmaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.CALENDAR]

_ENGLISH_OBJECT_IDS: dict[str, str] = {
    "problem": "problem",
    "recent_message": "recent_message",
    "recent_bulletin": "recent_bulletin",
    "recent_attendance": "recent_attendance",
    "latest_message": "latest_message",
    "unread_count": "unread_count",
    "latest_bulletin": "latest_bulletin",
    "unread_bulletin_count": "unread_bulletin_count",
    "last_update": "last_update",
    "next_lesson": "next_lesson",
    "attendance_count": "attendance_count",
    "latest_attendance": "latest_attendance",
    "last_http_status": "last_http_status",
    "calendar": "schedule",
}


def _english_object_id_for_unique_id(
    unique_id: str | None,
    student_name: str | None = None,
) -> str | None:
    """Return the canonical English object id for one Wilma entity unique id."""
    if not unique_id:
        return None

    parts = unique_id.split("_", 2)
    if len(parts) == 2:
        return f"wilma_{_ENGLISH_OBJECT_IDS.get(parts[1], parts[1])}"

    if len(parts) != 3:
        return None

    entity_key = _ENGLISH_OBJECT_IDS.get(parts[2], parts[2])
    if student_name:
        return f"wilma_{WilmaCoordinator._slugify_object_id(student_name)}_{entity_key}"

    return f"wilma_{parts[1]}_{entity_key}"


def _migrate_entity_names(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rename old registry entries to English IDs and clear generated names."""
    registry = entity_registry.async_get(hass)
    stale_prefixes = (
        "Unread ",
        "Latest ",
        "Recent ",
        "Next ",
        "Last ",
        "Olästa ",
        "Senaste ",
        "Nylig ",
        "Viimeisin ",
        "Lukemattomat ",
        "Seuraava ",
        "Antal ",
    )
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    student_name_by_id = {
        profile["id"]: profile["name"]
        for profile in getattr(coordinator, "student_profiles", [])
        if isinstance(profile, dict) and profile.get("id")
    }

    for entity in list(registry.entities.values()):
        if entity.config_entry_id != entry.entry_id:
            continue

        student_name = None
        if entity.unique_id:
            parts = entity.unique_id.split("_", 2)
            if len(parts) == 3:
                student_name = student_name_by_id.get(parts[1])

        desired_object_id = _english_object_id_for_unique_id(entity.unique_id, student_name)
        current_object_id = getattr(entity, "suggested_object_id", None)
        if current_object_id is None:
            current_object_id = getattr(entity, "object_id_base", None)

        if desired_object_id and current_object_id and current_object_id != desired_object_id:
            entity_object_id = entity.entity_id.split(".", 1)[1]
            try:
                if entity_object_id.endswith(current_object_id):
                    prefix = entity_object_id[: -len(current_object_id)]
                    new_entity_id = f"{entity.domain}.{prefix}{desired_object_id}"
                    if new_entity_id != entity.entity_id:
                        registry.async_update_entity(entity.entity_id, new_entity_id=new_entity_id)
            except Exception:  # pragma: no cover - migration should never block setup
                _LOGGER.exception("Failed to migrate entity id for %s", entity.entity_id)

        if entity.name is not None and entity.name.startswith(stale_prefixes):
            try:
                registry.async_update_entity(entity.entity_id, name=None)
            except Exception:  # pragma: no cover - migration should never block setup
                _LOGGER.exception("Failed to clear stale entity name for %s", entity.entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Wilma from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Create coordinator
    coordinator = WilmaCoordinator(
        hass,
        server_url=entry.data[CONF_SERVER_URL],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        entry_id=entry.entry_id,
        options=entry.options,
    )

    # Initial data fetch
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    _migrate_entity_names(hass, entry)

    # Set up all platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        # Clean up coordinator
        coordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.async_close_client()
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
