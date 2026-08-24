"""Text platform for Wilma integration."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_STUDENT_ID,
    ATTR_STUDENT_NAME,
    DOMAIN,
    INTEGRATION_VERSION,
    TEXT_LATEST_ATTENDANCE_SUMMARY_PART_1,
    TEXT_LATEST_ATTENDANCE_SUMMARY_PART_2,
    TEXT_LATEST_ATTENDANCE_SUMMARY_PART_3,
    TEXT_LATEST_BULLETIN_SUMMARY_PART_1,
    TEXT_LATEST_BULLETIN_SUMMARY_PART_2,
    TEXT_LATEST_BULLETIN_SUMMARY_PART_3,
    TEXT_LATEST_MESSAGE_SUMMARY_PART_1,
    TEXT_LATEST_MESSAGE_SUMMARY_PART_2,
    TEXT_LATEST_MESSAGE_SUMMARY_PART_3,
)
from .coordinator import WilmaCoordinator

_TEXT_DESCRIPTIONS: list[TextEntityDescription] = [
    TextEntityDescription(
        key=TEXT_LATEST_MESSAGE_SUMMARY_PART_1,
        name="Latest Message AI Summary Part 1",
    ),
    TextEntityDescription(
        key=TEXT_LATEST_MESSAGE_SUMMARY_PART_2,
        name="Latest Message AI Summary Part 2",
    ),
    TextEntityDescription(
        key=TEXT_LATEST_MESSAGE_SUMMARY_PART_3,
        name="Latest Message AI Summary Part 3",
    ),
    TextEntityDescription(
        key=TEXT_LATEST_BULLETIN_SUMMARY_PART_1,
        name="Latest Bulletin AI Summary Part 1",
    ),
    TextEntityDescription(
        key=TEXT_LATEST_BULLETIN_SUMMARY_PART_2,
        name="Latest Bulletin AI Summary Part 2",
    ),
    TextEntityDescription(
        key=TEXT_LATEST_BULLETIN_SUMMARY_PART_3,
        name="Latest Bulletin AI Summary Part 3",
    ),
    TextEntityDescription(
        key=TEXT_LATEST_ATTENDANCE_SUMMARY_PART_1,
        name="Latest Attendance AI Summary Part 1",
    ),
    TextEntityDescription(
        key=TEXT_LATEST_ATTENDANCE_SUMMARY_PART_2,
        name="Latest Attendance AI Summary Part 2",
    ),
    TextEntityDescription(
        key=TEXT_LATEST_ATTENDANCE_SUMMARY_PART_3,
        name="Latest Attendance AI Summary Part 3",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Wilma text platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    student_profiles = coordinator.data.get("student_profiles", []) if coordinator.data else []
    if not student_profiles:
        student_profiles = [{"id": "default", "name": entry.data.get("username", "Wilma")}]

    entities: list[WilmaSummaryTextEntity] = []
    for student in student_profiles:
        student_id = student["id"]
        student_name = student["name"]
        for description in _TEXT_DESCRIPTIONS:
            entities.append(
                WilmaSummaryTextEntity(
                    coordinator,
                    description,
                    entry,
                    student_id,
                    student_name,
                )
            )

    async_add_entities(entities)


class WilmaSummaryTextEntity(CoordinatorEntity, RestoreEntity, TextEntity):
    """Writable text entity intended for automation state storage."""

    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min = 0
    _attr_native_max = 255

    def __init__(
        self,
        coordinator: WilmaCoordinator,
        description: TextEntityDescription,
        entry: ConfigEntry,
        student_id: str,
        student_name: str,
    ) -> None:
        """Initialize the text entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._student_id = student_id
        self._student_name = student_name
        self._entry_id = entry.entry_id
        self._value = ""

        first_name = student_name.split()[0] if student_name else student_name
        self._attr_unique_id = f"{entry.entry_id}_{student_id}_{description.key}"
        self._attr_has_entity_name = True
        self._attr_name = coordinator.entity_name(description.key)
        self.internal_integration_suggested_object_id = coordinator.entity_object_id(
            description.key,
            student_name,
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_{student_id}")},
            "name": f"Wilma {first_name}",
            "manufacturer": "Visma",
            "model": "Wilma",
            "sw_version": INTEGRATION_VERSION,
        }

    @property
    def native_value(self) -> str:
        """Return the current text value."""
        return self._value

    @property
    def extra_state_attributes(self) -> dict[str, str | int]:
        """Expose student metadata and full summary on part-1 entities."""
        attrs: dict[str, str | int] = {
            ATTR_STUDENT_ID: self._student_id,
            ATTR_STUDENT_NAME: self._student_name,
        }

        if self.entity_description.key.endswith("_part_1"):
            full_summary = self._full_summary_from_parts()
            attrs["summary"] = full_summary
            attrs["summary_length"] = len(full_summary)

        return attrs

    def _full_summary_from_parts(self) -> str:
        """Build full summary text from part 1-3 entities for this source/student."""
        prefix = self.entity_description.key.rsplit("_part_", 1)[0]
        registry = entity_registry.async_get(self.hass)
        parts = [self._value]

        for index in (2, 3):
            unique_id = f"{self._entry_id}_{self._student_id}_{prefix}_part_{index}"
            entity_id = registry.async_get_entity_id("text", DOMAIN, unique_id)
            if not entity_id:
                continue

            state = self.hass.states.get(entity_id)
            if not state or state.state in (STATE_UNKNOWN, "unavailable"):
                continue

            parts.append(state.state)

        return "".join(parts)

    async def async_added_to_hass(self) -> None:
        """Restore text from previous state when available."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in (STATE_UNKNOWN, "unavailable"):
            self._value = str(last_state.state)[: self._attr_native_max]

    async def async_set_value(self, value: str) -> None:
        """Update the stored text value."""
        self._value = value[: self._attr_native_max]
        self.async_write_ha_state()
