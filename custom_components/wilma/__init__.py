"""The Wilma integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry

from .const import (
    ATTR_AGENT_ID,
    ATTR_ENTRY_ID,
    ATTR_ERROR,
    ATTR_GENERATED_BY,
    ATTR_INSTRUCTIONS,
    ATTR_MIN_LENGTH,
    ATTR_PROMPT,
    ATTR_SOURCE_ATTRIBUTE,
    ATTR_SOURCE_ENTITY,
    ATTR_SOURCE_ID,
    ATTR_STUDENT,
    ATTR_SUMMARY,
    ATTR_SUMMARY_KEY,
    ATTR_TITLE,
    CONF_PASSWORD,
    CONF_SERVER_URL,
    CONF_USERNAME,
    DEFAULT_SUMMARY_MIN_LENGTH,
    DOMAIN,
    GENERATED_BY_AGENT,
    GENERATED_BY_PASSTHROUGH,
    SERVICE_CLEAR_SUMMARY,
    SERVICE_STORE_SUMMARY,
    SERVICE_STORE_SUMMARY_ERROR,
    SERVICE_SUMMARY_STATUS,
)
from .coordinator import WilmaCoordinator
from .summary import WilmaSummaryStore, compose_source_text, source_fingerprint

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.CALENDAR,
    Platform.TEXT,
]

STORE_SUMMARY_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SUMMARY_KEY): cv.string,
        vol.Required(ATTR_SUMMARY): cv.string,
        vol.Optional(ATTR_STUDENT): cv.string,
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Optional(ATTR_TITLE): cv.string,
        vol.Optional(ATTR_PROMPT): cv.string,
        vol.Optional(ATTR_INSTRUCTIONS): cv.string,
        vol.Optional(ATTR_SOURCE_ENTITY): cv.string,
        vol.Optional(ATTR_SOURCE_ATTRIBUTE): cv.string,
        vol.Optional(ATTR_SOURCE_ID): cv.string,
        vol.Optional("source_text"): cv.string,
        vol.Optional(ATTR_AGENT_ID): cv.string,
        vol.Optional(ATTR_GENERATED_BY): vol.In(
            [GENERATED_BY_AGENT, GENERATED_BY_PASSTHROUGH]
        ),
    }
)

CLEAR_SUMMARY_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_SUMMARY_KEY): cv.string,
        vol.Optional(ATTR_STUDENT): cv.string,
        vol.Optional(ATTR_ENTRY_ID): cv.string,
    }
)

SUMMARY_STATUS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SUMMARY_KEY): cv.string,
        vol.Required(ATTR_SOURCE_ENTITY): cv.string,
        vol.Optional(ATTR_SOURCE_ATTRIBUTE): cv.string,
        vol.Optional(ATTR_STUDENT): cv.string,
        vol.Optional(ATTR_ENTRY_ID): cv.string,
        vol.Optional(ATTR_MIN_LENGTH, default=DEFAULT_SUMMARY_MIN_LENGTH): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
    }
)

STORE_SUMMARY_ERROR_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SUMMARY_KEY): cv.string,
        vol.Required(ATTR_ERROR): cv.string,
        vol.Optional(ATTR_STUDENT): cv.string,
        vol.Optional(ATTR_ENTRY_ID): cv.string,
    }
)

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
    "latest_message_summary_part_1": "latest_message_summary_part_1",
    "latest_message_summary_part_2": "latest_message_summary_part_2",
    "latest_message_summary_part_3": "latest_message_summary_part_3",
    "latest_bulletin_summary_part_1": "latest_bulletin_summary_part_1",
    "latest_bulletin_summary_part_2": "latest_bulletin_summary_part_2",
    "latest_bulletin_summary_part_3": "latest_bulletin_summary_part_3",
    "latest_attendance_summary_part_1": "latest_attendance_summary_part_1",
    "latest_attendance_summary_part_2": "latest_attendance_summary_part_2",
    "latest_attendance_summary_part_3": "latest_attendance_summary_part_3",
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

    summary_store = WilmaSummaryStore(hass, entry.entry_id)
    await summary_store.async_load()
    coordinator.summaries = summary_store

    # Store coordinator
    hass.data[DOMAIN][entry.entry_id] = coordinator

    _migrate_entity_names(hass, entry)

    _async_register_services(hass)

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

        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_STORE_SUMMARY)
            hass.services.async_remove(DOMAIN, SERVICE_CLEAR_SUMMARY)
            hass.services.async_remove(DOMAIN, SERVICE_SUMMARY_STATUS)
            hass.services.async_remove(DOMAIN, SERVICE_STORE_SUMMARY_ERROR)

    return unload_ok


def _resolve_coordinator(hass: HomeAssistant, entry_id: str | None) -> WilmaCoordinator:
    """Return the coordinator for an explicit entry id, or the only loaded one."""
    coordinators: dict[str, WilmaCoordinator] = hass.data.get(DOMAIN, {})

    if entry_id:
        coordinator = coordinators.get(entry_id)
        if coordinator is None:
            raise ServiceValidationError(f"No loaded Wilma config entry with id {entry_id}")
        return coordinator

    if len(coordinators) != 1:
        raise ServiceValidationError(
            "Multiple Wilma config entries are loaded; pass entry_id to select one"
        )

    return next(iter(coordinators.values()))


def _resolve_student(
    coordinator: WilmaCoordinator,
    student: str | None,
) -> tuple[str, str | None]:
    """Resolve a student id or name into a (student_id, student_name) pair."""
    profiles = [
        profile
        for profile in getattr(coordinator, "student_profiles", [])
        if isinstance(profile, dict) and profile.get("id")
    ]

    if not student:
        if len(profiles) == 1:
            return profiles[0]["id"], profiles[0].get("name")
        raise ServiceValidationError(
            "Multiple students are configured; pass student to select one"
        )

    for profile in profiles:
        if profile["id"] == student:
            return profile["id"], profile.get("name")

    wanted = WilmaCoordinator._slugify_object_id(student)
    for profile in profiles:
        name = profile.get("name") or ""
        if name.lower() == student.lower():
            return profile["id"], name
        if name and WilmaCoordinator._slugify_object_id(name) == wanted:
            return profile["id"], name

    known = ", ".join(
        f"{profile['id']} ({profile.get('name')})" for profile in profiles
    )
    raise ServiceValidationError(f"Unknown student {student!r}. Known students: {known}")


def _async_register_services(hass: HomeAssistant) -> None:
    """Register the summary services once for the whole integration."""
    if hass.services.has_service(DOMAIN, SERVICE_STORE_SUMMARY):
        return

    async def _async_store_summary(call: ServiceCall) -> None:
        coordinator = _resolve_coordinator(hass, call.data.get(ATTR_ENTRY_ID))
        student_id, student_name = _resolve_student(coordinator, call.data.get(ATTR_STUDENT))

        summary = call.data[ATTR_SUMMARY].strip()
        if not summary:
            raise ServiceValidationError("Refusing to store an empty summary")

        source_entity = call.data.get(ATTR_SOURCE_ENTITY)
        source_attribute = call.data.get(ATTR_SOURCE_ATTRIBUTE)
        source_text = call.data.get("source_text")
        if source_text is None and source_entity:
            source_text = compose_source_text(hass, source_entity, source_attribute)

        await coordinator.summaries.async_store(
            student_id,
            student_name,
            call.data[ATTR_SUMMARY_KEY],
            summary,
            title=call.data.get(ATTR_TITLE),
            prompt=call.data.get(ATTR_PROMPT),
            instructions=call.data.get(ATTR_INSTRUCTIONS),
            source_entity=source_entity,
            source_attribute=source_attribute,
            source_id=call.data.get(ATTR_SOURCE_ID),
            source_text=source_text,
            agent_id=call.data.get(ATTR_AGENT_ID),
            generated_by=call.data.get(ATTR_GENERATED_BY, GENERATED_BY_AGENT),
        )

    async def _async_clear_summary(call: ServiceCall) -> None:
        coordinator = _resolve_coordinator(hass, call.data.get(ATTR_ENTRY_ID))
        student = call.data.get(ATTR_STUDENT)
        student_id = None
        if student:
            student_id, _ = _resolve_student(coordinator, student)

        await coordinator.summaries.async_clear(student_id, call.data.get(ATTR_SUMMARY_KEY))

    async def _async_store_summary_error(call: ServiceCall) -> None:
        coordinator = _resolve_coordinator(hass, call.data.get(ATTR_ENTRY_ID))
        student_id, student_name = _resolve_student(coordinator, call.data.get(ATTR_STUDENT))

        await coordinator.summaries.async_store_error(
            student_id,
            student_name,
            call.data[ATTR_SUMMARY_KEY],
            call.data[ATTR_ERROR],
        )

    async def _async_summary_status(call: ServiceCall) -> ServiceResponse:
        coordinator = _resolve_coordinator(hass, call.data.get(ATTR_ENTRY_ID))
        student_id, _ = _resolve_student(coordinator, call.data.get(ATTR_STUDENT))

        key = call.data[ATTR_SUMMARY_KEY]
        source_entity = call.data[ATTR_SOURCE_ENTITY]
        source_attribute = call.data.get(ATTR_SOURCE_ATTRIBUTE)
        min_length = call.data[ATTR_MIN_LENGTH]

        source_text = compose_source_text(hass, source_entity, source_attribute)
        source_hash = source_fingerprint(source_text)
        record = coordinator.summaries.get(student_id, key)
        stored_hash = record.get("source_hash") if record else None

        if not source_text:
            reason = "no_source"
        elif stored_hash and stored_hash == source_hash:
            reason = "unchanged"
        elif len(source_text) < min_length:
            reason = "too_short"
        elif record is None:
            reason = "no_summary"
        else:
            reason = "source_changed"

        return {
            "needs_update": reason in ("too_short", "no_summary", "source_changed"),
            "call_agent": reason in ("no_summary", "source_changed"),
            "reason": reason,
            "source_text": source_text,
            "source_hash": source_hash,
            "source_length": len(source_text),
            "stored_hash": stored_hash,
            "min_length": min_length,
            "student_id": student_id,
        }

    hass.services.async_register(
        DOMAIN, SERVICE_STORE_SUMMARY, _async_store_summary, schema=STORE_SUMMARY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_SUMMARY, _async_clear_summary, schema=CLEAR_SUMMARY_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SUMMARY_STATUS,
        _async_summary_status,
        schema=SUMMARY_STATUS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_STORE_SUMMARY_ERROR,
        _async_store_summary_error,
        schema=STORE_SUMMARY_ERROR_SCHEMA,
    )
