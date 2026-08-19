"""Sensor platform for Wilma integration."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_CONTENT,
    ATTR_CONTENT_MARKDOWN,
    ATTR_ID,
    ATTR_SENDER,
    ATTR_STUDENT_ID,
    ATTR_STUDENT_NAME,
    ATTR_SUBJECT,
    ATTR_TIMESTAMP,
    DOMAIN,
    SENSOR_LATEST_MESSAGE,
    SENSOR_UNREAD_COUNT,
)
from .coordinator import WilmaCoordinator

_LOGGER = logging.getLogger(__name__)

SENSOR_DESCRIPTIONS = [
    SensorEntityDescription(
        key=SENSOR_LATEST_MESSAGE,
        name="Latest Message",
        icon="mdi:email",
    ),
    SensorEntityDescription(
        key=SENSOR_UNREAD_COUNT,
        name="Unread Messages",
        icon="mdi:email-alert",
    )
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Wilma sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []

    student_profiles = coordinator.data.get("student_profiles", []) if coordinator.data else []
    if not student_profiles:
        student_profiles = [{"id": "default", "name": entry.data.get("username", "Wilma")}]

    for student in student_profiles:
        student_id = student["id"]
        student_name = student["name"]
        entities.append(
            WilmaLatestMessageSensor(
                coordinator,
                SENSOR_DESCRIPTIONS[0],
                entry,
                student_id,
                student_name,
            )
        )
        entities.append(
            WilmaUnreadCountSensor(
                coordinator,
                SENSOR_DESCRIPTIONS[1],
                entry,
                student_id,
                student_name,
            )
        )
        entities.append(
            WilmaLastUpdateSensor(
                coordinator,
                SensorEntityDescription(
                    key="last_update",
                    name="Last Update",
                    icon="mdi:update",
                    device_class=SensorDeviceClass.TIMESTAMP,
                    entity_category=EntityCategory.DIAGNOSTIC,
                ),
                entry,
                student_id,
                student_name,
            )
        )

    async_add_entities(entities)


class WilmaBaseStudentSensor(CoordinatorEntity, SensorEntity):
    """Base sensor for one discovered Wilma student profile."""

    def __init__(
        self,
        coordinator: WilmaCoordinator,
        description: SensorEntityDescription,
        entry: ConfigEntry,
        student_id: str,
        student_name: str,
    ) -> None:
        """Initialize the per-student sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._student_id = student_id
        self._student_name = student_name
        self._attr_unique_id = f"{entry.entry_id}_{student_id}_{description.key}"
        self._attr_name = f"{student_name} {description.name}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_{student_id}")},
            "name": f"Wilma {student_name}",
            "manufacturer": "Visma",
            "model": "Wilma",
            "sw_version": "1.0.0",
        }

    @property
    def extra_state_attributes(self) -> Optional[Dict[str, Any]]:
        """Return base student metadata for all entities."""
        return {
            ATTR_STUDENT_ID: self._student_id,
            ATTR_STUDENT_NAME: self._student_name,
        }


class WilmaLatestMessageSensor(WilmaBaseStudentSensor):
    """Sensor representing latest message for one student."""

    def __init__(
        self,
        coordinator: WilmaCoordinator,
        description: SensorEntityDescription,
        entry: ConfigEntry,
        student_id: str,
        student_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description, entry, student_id, student_name)
        self._message: dict[str, Any] | None = None

    @property
    def native_value(self) -> StateType:
        """Return the value reported by the sensor."""
        if not self.coordinator.data:
            return None

        message = self.coordinator.data.get("latest_message_by_student", {}).get(
            self._student_id
        )

        self._message = message
        if not message:
            return None

        return message["subject"]

    @property
    def extra_state_attributes(self) -> Optional[Dict[str, Any]]:
        """Return entity specific state attributes."""
        if not self._message:
            return super().extra_state_attributes

        attrs = super().extra_state_attributes or {}
        attrs.update(
            {
            ATTR_ID: self._message["id"],
            ATTR_SUBJECT: self._message["subject"],
            ATTR_SENDER: self._message["sender"],
            ATTR_TIMESTAMP: self._message["timestamp"],
            "folder": self._message.get("folder"),
            "unread": self._message.get("unread"),
            "allow_reply": self._message.get("allow_reply"),
            "allow_forward": self._message.get("allow_forward"),
            "senders": self._message.get("senders"),
            }
        )

        # Add content if available
        if "content_html" in self._message and self._message["content_html"]:
            attrs[ATTR_CONTENT] = self._message["content_html"]
            try:
                attrs[ATTR_CONTENT_MARKDOWN] = self._message["content_markdown"]
            except Exception:
                pass

        return attrs


class WilmaUnreadCountSensor(WilmaBaseStudentSensor):
    """Sensor representing unread message count for one student."""

    @property
    def native_value(self) -> StateType:
        """Return unread count for one student."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("unread_count_by_student", {}).get(self._student_id, 0)


class WilmaLastUpdateSensor(CoordinatorEntity, SensorEntity):
    """Sensor for tracking the last successful update time."""

    def __init__(
        self,
        coordinator: WilmaCoordinator,
        description: SensorEntityDescription,
        entry: ConfigEntry,
        student_id: str,
        student_name: str,
    ) -> None:
        """Initialize the last update sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._student_id = student_id
        self._student_name = student_name
        self._attr_unique_id = f"{entry.entry_id}_{student_id}_{description.key}"
        self._attr_name = f"{student_name} {description.name}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_{student_id}")},
            "name": f"Wilma {student_name}",
            "manufacturer": "Visma",
            "model": "Wilma",
            "sw_version": "1.0.0",
        }

    @property
    def extra_state_attributes(self) -> Optional[Dict[str, Any]]:
        """Return student metadata for diagnostics."""
        return {
            ATTR_STUDENT_ID: self._student_id,
            ATTR_STUDENT_NAME: self._student_name,
        }

    @property
    def native_value(self) -> datetime | None:
        """Return the value reported by the sensor."""
        if self.coordinator.data and "last_update" in self.coordinator.data:
            return self.coordinator.data["last_update"]
        if self.coordinator.last_update_success_time:
            return dt_util.as_local(self.coordinator.last_update_success_time)
        return None
