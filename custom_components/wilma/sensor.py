"""Sensor platform for Wilma integration."""

from __future__ import annotations

import logging
import zoneinfo
from collections.abc import Callable
from datetime import datetime, time as dt_time
from typing import Any, Dict, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_AGENT_ID,
    ATTR_CONTENT,
    ATTR_CONTENT_MARKDOWN,
    ATTR_ERROR_COUNT,
    ATTR_GENERATED_AT,
    ATTR_GENERATED_BY,
    ATTR_ID,
    ATTR_INSTRUCTIONS,
    ATTR_IS_STALE,
    ATTR_LAST_ERROR,
    ATTR_LAST_ERROR_AT,
    ATTR_NEWS_DATE,
    ATTR_NEWS_ID,
    ATTR_NEWS_SECTION,
    ATTR_NEWS_URL,
    ATTR_PROMPT,
    ATTR_SENDER,
    ATTR_SOURCE_ATTRIBUTE,
    ATTR_SOURCE_ENTITY,
    ATTR_SOURCE_HASH,
    ATTR_SOURCE_ID,
    ATTR_SOURCE_LENGTH,
    ATTR_STUDENT_ID,
    ATTR_STUDENT_NAME,
    ATTR_SUBJECT,
    ATTR_SUMMARY,
    ATTR_TIMESTAMP,
    ATTR_TITLE,
    DOMAIN,
    INTEGRATION_VERSION,
    SENSOR_ATTENDANCE_COUNT,
    SENSOR_LATEST_BULLETIN,
    SENSOR_LATEST_ATTENDANCE,
    SENSOR_LAST_HTTP_STATUS,
    SENSOR_LATEST_MESSAGE,
    SENSOR_NEXT_LESSON,
    SENSOR_UNREAD_BULLETIN_COUNT,
    SENSOR_UNREAD_COUNT,
    SIGNAL_SUMMARY_ADDED,
    SIGNAL_SUMMARY_UPDATED,
)
from .coordinator import WilmaCoordinator
from .summary import compose_source_text, source_fingerprint

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
    ),
    SensorEntityDescription(
        key=SENSOR_LATEST_BULLETIN,
        name="Latest Bulletin",
        icon="mdi:bullhorn",
    ),
    SensorEntityDescription(
        key=SENSOR_UNREAD_BULLETIN_COUNT,
        name="Unread Bulletins",
        icon="mdi:bullhorn-outline",
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Wilma sensor platform."""
    coordinator = hass.data[DOMAIN][entry.entry_id]

    entities = []

    entities.append(
        WilmaLastHttpStatusSensor(
            coordinator,
            SensorEntityDescription(
                key=SENSOR_LAST_HTTP_STATUS,
                name="Last HTTP Status",
                icon="mdi:web",
                entity_category=EntityCategory.DIAGNOSTIC,
            ),
            entry,
        )
    )

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
            WilmaLatestBulletinSensor(
                coordinator,
                SENSOR_DESCRIPTIONS[2],
                entry,
                student_id,
                student_name,
            )
        )
        entities.append(
            WilmaUnreadBulletinCountSensor(
                coordinator,
                SENSOR_DESCRIPTIONS[3],
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
        entities.append(
            WilmaNextLessonSensor(
                coordinator,
                SensorEntityDescription(
                    key=SENSOR_NEXT_LESSON,
                    name="Next Lesson",
                    icon="mdi:school",
                ),
                entry,
                student_id,
                student_name,
            )
        )
        entities.append(
            WilmaAttendanceCountSensor(
                coordinator,
                SensorEntityDescription(
                    key=SENSOR_ATTENDANCE_COUNT,
                    name="Attendance Marks",
                    icon="mdi:clipboard-alert",
                ),
                entry,
                student_id,
                student_name,
            )
        )
        entities.append(
            WilmaLatestAttendanceSensor(
                coordinator,
                SensorEntityDescription(
                    key=SENSOR_LATEST_ATTENDANCE,
                    name="Latest Attendance Mark",
                    icon="mdi:clipboard-clock",
                ),
                entry,
                student_id,
                student_name,
            )
        )

    async_add_entities(entities)

    summary_store = getattr(coordinator, "summaries", None)
    if summary_store is None:
        return

    student_names = {student["id"]: student["name"] for student in student_profiles}
    known_summaries: set[tuple[str, str]] = set()

    summary_entities = []
    for student_id, key in summary_store.stored_keys():
        record = summary_store.get(student_id, key) or {}
        known_summaries.add((student_id, key))
        summary_entities.append(
            WilmaSummarySensor(
                coordinator,
                entry,
                student_id,
                student_names.get(student_id) or record.get("student_name") or student_id,
                key,
            )
        )

    if summary_entities:
        async_add_entities(summary_entities)

    @callback
    def _async_summary_added(student_id: str, student_name: str | None, key: str) -> None:
        if (student_id, key) in known_summaries:
            return
        known_summaries.add((student_id, key))
        async_add_entities(
            [
                WilmaSummarySensor(
                    coordinator,
                    entry,
                    student_id,
                    student_names.get(student_id) or student_name or student_id,
                    key,
                )
            ]
        )

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            SIGNAL_SUMMARY_ADDED.format(entry.entry_id),
            _async_summary_added,
        )
    )


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


class WilmaLatestBulletinSensor(WilmaBaseStudentSensor):
    """Sensor representing the latest bulletin for one student."""

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.data:
            return None

        item = self.coordinator.data.get("latest_bulletin_by_student", {}).get(self._student_id)
        return item.get("title") if item else None

    @property
    def extra_state_attributes(self) -> Optional[Dict[str, Any]]:
        attrs = super().extra_state_attributes or {}
        if not self.coordinator.data:
            return attrs

        item = self.coordinator.data.get("latest_bulletin_by_student", {}).get(self._student_id)
        if not item:
            return attrs

        attrs.update(
            {
                ATTR_NEWS_ID: item.get("news_id"),
                ATTR_SUBJECT: item.get("title"),
                ATTR_NEWS_DATE: item.get("date"),
                ATTR_NEWS_SECTION: item.get("section"),
                ATTR_NEWS_URL: item.get("url"),
            }
        )

        if item.get("content_markdown"):
            attrs[ATTR_CONTENT_MARKDOWN] = item.get("content_markdown")
        return attrs


class WilmaUnreadBulletinCountSensor(WilmaBaseStudentSensor):
    """Sensor representing bulletin updates discovered in the latest refresh."""

    @property
    def native_value(self) -> int:
        if not self.coordinator.data:
            return 0
        return self.coordinator.data.get("unread_bulletin_count_by_student", {}).get(self._student_id, 0)


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
        first_name = student_name.split()[0] if student_name else student_name
        self._attr_unique_id = f"{entry.entry_id}_{student_id}_{description.key}"
        self._attr_has_entity_name = True
        self._attr_name = coordinator.entity_name(description.key)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_{student_id}")},
            "name": f"Wilma {first_name}",
            "manufacturer": "Visma",
            "model": "Wilma",
            "sw_version": INTEGRATION_VERSION,
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


class WilmaNextLessonSensor(WilmaBaseStudentSensor):
    """Sensor showing the next upcoming school lesson for one student."""

    @property
    def native_value(self) -> str | None:
        lesson = self._next_lesson()
        return lesson.get("subject") if lesson else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs = super().extra_state_attributes or {}
        lesson = self._next_lesson()
        if not lesson:
            return attrs

        date_str = lesson.get("date", "")
        start_min = int(lesson.get("start_minutes", 0))
        end_min = int(lesson.get("end_minutes", 0))
        start_iso = end_iso = None
        try:
            d = datetime.strptime(date_str, "%d.%m.%Y").date()
            tz = zoneinfo.ZoneInfo(self.coordinator.hass.config.time_zone)
            start_iso = datetime.combine(d, dt_time(start_min // 60, start_min % 60), tzinfo=tz).isoformat()
            end_iso = datetime.combine(d, dt_time(end_min // 60, end_min % 60), tzinfo=tz).isoformat()
        except ValueError:
            pass

        attrs.update({
            "date": date_str,
            "start_time": start_iso,
            "end_time": end_iso,
            "room": lesson.get("room"),
            "teachers": lesson.get("teachers"),
            "color": lesson.get("color"),
            "subject_long": lesson.get("subject_long"),
        })
        return attrs

    def _next_lesson(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        raw_events = self.coordinator.data.get("schedules", {}).get(self._student_id, [])
        now = dt_util.now()
        tz = zoneinfo.ZoneInfo(self.coordinator.hass.config.time_zone)
        for evt in raw_events:
            date_str = evt.get("date", "")
            end_min = int(evt.get("end_minutes", 0))
            try:
                d = datetime.strptime(date_str, "%d.%m.%Y").date()
                end_dt = datetime.combine(d, dt_time(end_min // 60, end_min % 60), tzinfo=tz)
            except ValueError:
                continue
            if end_dt > now:
                return evt
        return None


class WilmaAttendanceCountSensor(WilmaBaseStudentSensor):
    """Number of attendance marks in the current school year."""

    @property
    def native_value(self) -> int:
        return len(self._marks())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs = super().extra_state_attributes or {}
        marks = self._marks()
        unexplained = self._unexplained()
        attrs["unexplained_count"] = len(unexplained)
        # Count by mark type
        by_type: dict[str, int] = {}
        for m in marks:
            t = m.get("mark_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        if by_type:
            attrs["by_type"] = by_type
        return attrs

    def _marks(self) -> list[dict[str, Any]]:
        if not self.coordinator.data:
            return []
        return self.coordinator.data.get("attendance", {}).get(self._student_id, [])

    def _unexplained(self) -> list[dict[str, Any]]:
        if not self.coordinator.data:
            return []
        return self.coordinator.data.get("unexplained_attendance", {}).get(self._student_id, [])


class WilmaLatestAttendanceSensor(WilmaBaseStudentSensor):
    """Most recent attendance mark for this student."""

    @property
    def native_value(self) -> str | None:
        marks = self._marks()
        if not marks:
            return None
        return marks[0].get("mark_type") or None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs = super().extra_state_attributes or {}
        marks = self._marks()
        if marks:
            attrs.update({k: v for k, v in marks[0].items() if not k.startswith("_")})
        return attrs

    def _marks(self) -> list[dict[str, Any]]:
        if not self.coordinator.data:
            return []
        return self.coordinator.data.get("attendance", {}).get(self._student_id, [])


class WilmaLastHttpStatusSensor(CoordinatorEntity, SensorEntity):
    """Diagnostic sensor exposing the last HTTP status code seen during scraping."""

    def __init__(
        self,
        coordinator: WilmaCoordinator,
        description: SensorEntityDescription,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_has_entity_name = True
        self._attr_name = coordinator.entity_name(description.key)
        self.internal_integration_suggested_object_id = coordinator.entity_object_id(
            description.key
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Wilma",
            "manufacturer": "Visma",
            "model": "Wilma",
            "sw_version": INTEGRATION_VERSION,
        }

    @property
    def available(self) -> bool:
        """Always available — the value is tracked independently of coordinator success."""
        return True

    @property
    def native_value(self) -> int | None:
        """Return the last HTTP status code observed, regardless of update success."""
        return self.coordinator.last_http_status


class WilmaSummarySensor(CoordinatorEntity, SensorEntity):
    """Expose one stored AI summary, with the full text in the summary attribute."""

    _attr_icon = "mdi:text-box-search-outline"

    def __init__(
        self,
        coordinator: WilmaCoordinator,
        entry: ConfigEntry,
        student_id: str,
        student_name: str,
        key: str,
    ) -> None:
        """Initialize the summary sensor."""
        super().__init__(coordinator)
        self._student_id = student_id
        self._student_name = student_name
        self._key = key
        self._source_unsub: Callable[[], None] | None = None
        first_name = student_name.split()[0] if student_name else student_name
        self._attr_unique_id = f"{entry.entry_id}_{student_id}_summary_{key}"
        self._attr_has_entity_name = True
        self._attr_name = f"{key.replace('_', ' ').capitalize()} summary"
        self.internal_integration_suggested_object_id = coordinator.entity_object_id(
            f"summary_{key}",
            student_name,
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_{student_id}")},
            "name": f"Wilma {first_name}",
            "manufacturer": "Visma",
            "model": "Wilma",
            "sw_version": INTEGRATION_VERSION,
        }

    async def async_added_to_hass(self) -> None:
        """Refresh state whenever this summary is rewritten or cleared."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_SUMMARY_UPDATED.format(self.coordinator.entry_id),
                self._async_summary_updated,
            )
        )
        self.async_on_remove(self._async_stop_tracking_source)
        self._async_track_source()

    @callback
    def _async_stop_tracking_source(self) -> None:
        if self._source_unsub is not None:
            self._source_unsub()
            self._source_unsub = None

    @callback
    def _async_track_source(self) -> None:
        """Watch the summarised entity so is_stale stays current."""
        self._async_stop_tracking_source()
        record = self._record
        source_entity = record.get("source_entity") if record else None
        if not source_entity:
            return

        self._source_unsub = async_track_state_change_event(
            self.hass, [source_entity], self._async_source_changed
        )

    @callback
    def _async_source_changed(self, event: Event[EventStateChangedData]) -> None:
        self.async_write_ha_state()

    @callback
    def _async_summary_updated(self, student_id: str, key: str) -> None:
        if student_id == self._student_id and key == self._key:
            self._async_track_source()
            self.async_write_ha_state()

    @property
    def _record(self) -> dict[str, Any] | None:
        store = getattr(self.coordinator, "summaries", None)
        if store is None:
            return None
        return store.get(self._student_id, self._key)

    @property
    def available(self) -> bool:
        """Stored summaries stay readable even when a Wilma fetch fails."""
        return True

    @property
    def native_value(self) -> StateType:
        """Return a short label; the full text lives in the summary attribute."""
        record = self._record
        if not record:
            return None

        label = record.get("title") or (record.get("summary") or "").strip()
        label = label.splitlines()[0] if label else ""
        if not label:
            return None

        return label[:252] + "..." if len(label) > 255 else label

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the full summary plus the prompt that produced it."""
        record = self._record
        attrs: dict[str, Any] = {
            ATTR_STUDENT_ID: self._student_id,
            ATTR_STUDENT_NAME: self._student_name,
            "summary_key": self._key,
        }
        if not record:
            return attrs

        attrs.update(
            {
                ATTR_SUMMARY: record.get("summary"),
                ATTR_TITLE: record.get("title"),
                ATTR_PROMPT: record.get("prompt"),
                ATTR_INSTRUCTIONS: record.get("instructions"),
                ATTR_SOURCE_ENTITY: record.get("source_entity"),
                ATTR_SOURCE_ATTRIBUTE: record.get("source_attribute"),
                ATTR_SOURCE_ID: record.get("source_id"),
                ATTR_SOURCE_HASH: record.get("source_hash"),
                ATTR_SOURCE_LENGTH: record.get("source_length"),
                ATTR_AGENT_ID: record.get("agent_id"),
                ATTR_GENERATED_BY: record.get("generated_by"),
                ATTR_GENERATED_AT: record.get("generated_at"),
                ATTR_IS_STALE: self._is_stale(record),
                ATTR_LAST_ERROR: record.get("last_error"),
                ATTR_LAST_ERROR_AT: record.get("last_error_at"),
                ATTR_ERROR_COUNT: record.get("error_count", 0),
                "history": record.get("history", []),
            }
        )
        return attrs

    def _is_stale(self, record: dict[str, Any]) -> bool | None:
        """Return whether the source text has changed since the summary was made."""
        source_entity = record.get("source_entity")
        if not source_entity or not record.get("source_hash"):
            return None

        current = compose_source_text(
            self.hass, source_entity, record.get("source_attribute")
        )
        if not current:
            return None

        return source_fingerprint(current) != record.get("source_hash")

