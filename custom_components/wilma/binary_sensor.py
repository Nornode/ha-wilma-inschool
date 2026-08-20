"""Binary sensor platform for Wilma integration."""

from __future__ import annotations

import zoneinfo
from datetime import datetime, time as dt_time, timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    BINARY_SENSOR_PROBLEM,
    BINARY_SENSOR_RECENT_ATTENDANCE,
    BINARY_SENSOR_RECENT_BULLETIN,
    BINARY_SENSOR_RECENT_MESSAGE,
    CONF_RECENT_THRESHOLD_HOURS,
    DEFAULT_RECENT_THRESHOLD_HOURS,
    DOMAIN,
    INTEGRATION_VERSION,
)
from .coordinator import WilmaCoordinator

_PROBLEM_DESCRIPTION = BinarySensorEntityDescription(
    key=BINARY_SENSOR_PROBLEM,
    name="Problem",
    device_class=BinarySensorDeviceClass.PROBLEM,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Wilma binary sensor platform."""
    coordinator: WilmaCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BinarySensorEntity] = [WilmaProblemBinarySensor(coordinator, entry)]

    student_profiles = coordinator.data.get("student_profiles", []) if coordinator.data else []
    if not student_profiles:
        student_profiles = [{"id": "default", "name": entry.data.get("username", "Wilma")}]

    for student in student_profiles:
        student_id = student["id"]
        student_name = student["name"]
        entities.append(WilmaRecentMessageBinarySensor(coordinator, entry, student_id, student_name))
        entities.append(WilmaRecentBulletinBinarySensor(coordinator, entry, student_id, student_name))
        entities.append(WilmaRecentAttendanceBinarySensor(coordinator, entry, student_id, student_name))

    async_add_entities(entities)


class WilmaProblemBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor that turns ON when any Wilma scrape fails or returns an unexpected HTTP status."""

    entity_description = _PROBLEM_DESCRIPTION

    def __init__(self, coordinator: WilmaCoordinator, entry: ConfigEntry) -> None:
        """Initialize the problem sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_problem"
        self._attr_has_entity_name = True
        self._attr_translation_key = BINARY_SENSOR_PROBLEM
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Wilma",
            "manufacturer": "Visma",
            "model": "Wilma",
            "sw_version": INTEGRATION_VERSION,
        }

    @property
    def available(self) -> bool:
        """Always available — this sensor exists to report failures."""
        return True

    @property
    def is_on(self) -> bool:
        """Return True when the last coordinator update failed or partial fetch errors occurred."""
        if not self.coordinator.last_update_success:
            return True
        return bool(self.coordinator.last_fetch_errors)

    @property
    def extra_state_attributes(self) -> dict:
        """Return fetch error details when in problem state."""
        return {"errors": list(self.coordinator.last_fetch_errors)}


class WilmaBaseStudentBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Base binary sensor for one discovered Wilma student profile."""

    def __init__(
        self,
        coordinator: WilmaCoordinator,
        description: BinarySensorEntityDescription,
        entry: ConfigEntry,
        student_id: str,
        student_name: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._student_id = student_id
        self._student_name = student_name
        self._entry = entry
        first_name = student_name.split()[0] if student_name else student_name
        self._attr_unique_id = f"{entry.entry_id}_{student_id}_{description.key}"
        self._attr_has_entity_name = True
        self._attr_translation_key = description.key
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_{student_id}")},
            "name": f"Wilma {first_name}",
            "manufacturer": "Visma",
            "model": "Wilma",
            "sw_version": INTEGRATION_VERSION,
        }

    def _threshold(self) -> timedelta:
        hours = self._entry.options.get(CONF_RECENT_THRESHOLD_HOURS, DEFAULT_RECENT_THRESHOLD_HOURS)
        return timedelta(hours=hours)


class WilmaRecentMessageBinarySensor(WilmaBaseStudentBinarySensor):
    """ON when the latest message for this student arrived within the configured threshold."""

    def __init__(self, coordinator: WilmaCoordinator, entry: ConfigEntry, student_id: str, student_name: str) -> None:
        super().__init__(
            coordinator,
            BinarySensorEntityDescription(key=BINARY_SENSOR_RECENT_MESSAGE),
            entry,
            student_id,
            student_name,
        )

    @property
    def is_on(self) -> bool:
        if not self.coordinator.data:
            return False
        msg = self.coordinator.data.get("latest_message_by_student", {}).get(self._student_id)
        if not msg:
            return False
        ts_str = msg.get("timestamp", "")
        try:
            tz = zoneinfo.ZoneInfo(self.coordinator.hass.config.time_zone)
            ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        except (ValueError, TypeError):
            return False
        return dt_util.now() - ts <= self._threshold()


class WilmaRecentBulletinBinarySensor(WilmaBaseStudentBinarySensor):
    """ON when the latest bulletin for this student was first seen within the configured threshold."""

    def __init__(self, coordinator: WilmaCoordinator, entry: ConfigEntry, student_id: str, student_name: str) -> None:
        super().__init__(
            coordinator,
            BinarySensorEntityDescription(key=BINARY_SENSOR_RECENT_BULLETIN),
            entry,
            student_id,
            student_name,
        )

    @property
    def is_on(self) -> bool:
        if not self.coordinator.data:
            return False
        bulletin = self.coordinator.data.get("latest_bulletin_by_student", {}).get(self._student_id)
        if not bulletin:
            return False
        fetched_at = bulletin.get("fetched_at")
        if not fetched_at:
            return False
        try:
            ts = datetime.fromisoformat(fetched_at).replace(tzinfo=dt_util.UTC)
        except (ValueError, TypeError):
            return False
        return dt_util.utcnow() - ts <= self._threshold()


class WilmaRecentAttendanceBinarySensor(WilmaBaseStudentBinarySensor):
    """ON when the most recent attendance mark for this student is within the configured threshold."""

    def __init__(self, coordinator: WilmaCoordinator, entry: ConfigEntry, student_id: str, student_name: str) -> None:
        super().__init__(
            coordinator,
            BinarySensorEntityDescription(key=BINARY_SENSOR_RECENT_ATTENDANCE),
            entry,
            student_id,
            student_name,
        )

    @property
    def is_on(self) -> bool:
        if not self.coordinator.data:
            return False
        marks = self.coordinator.data.get("attendance", {}).get(self._student_id, [])
        if not marks:
            return False
        date_str = marks[0].get("date", "")
        try:
            tz = zoneinfo.ZoneInfo(self.coordinator.hass.config.time_zone)
            # Use end-of-day so a mark from "today" stays recent throughout the day
            d = datetime.strptime(date_str, "%d.%m.%Y").date()
            ts = datetime.combine(d, dt_time(23, 59), tzinfo=tz)
        except (ValueError, TypeError):
            return False
        return dt_util.now() - ts <= self._threshold()
