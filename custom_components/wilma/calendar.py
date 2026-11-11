"""Calendar platform for Wilma integration — one calendar per student."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, INTEGRATION_VERSION
from .coordinator import WilmaCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Wilma calendar platform."""
    coordinator: WilmaCoordinator = hass.data[DOMAIN][entry.entry_id]

    profiles = coordinator.data.get("student_profiles", []) if coordinator.data else []
    if not profiles:
        profiles = [{"id": "default", "name": entry.data.get("username", "Wilma")}]

    entities: list[CalendarEntity] = []
    for p in profiles:
        entities.append(WilmaCalendarEntity(coordinator, entry, p["id"], p["name"]))
        entities.append(WilmaExamCalendarEntity(coordinator, entry, p["id"], p["name"]))
    async_add_entities(entities)


class WilmaCalendarEntity(CoordinatorEntity, CalendarEntity):
    """Calendar entity representing one student's timetable."""

    def __init__(
        self,
        coordinator: WilmaCoordinator,
        entry: ConfigEntry,
        student_id: str,
        student_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._student_id = student_id
        self._student_name = student_name
        first_name = student_name.split()[0] if student_name else student_name
        self._attr_unique_id = f"{entry.entry_id}_{student_id}_calendar"
        self._attr_has_entity_name = True
        self._attr_name = coordinator.entity_name("schedule")
        self.internal_integration_suggested_object_id = coordinator.entity_object_id(
            "schedule",
            student_name,
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_{student_id}")},
            "name": f"Wilma {first_name}",
            "manufacturer": "Visma",
            "model": "Wilma",
            "sw_version": INTEGRATION_VERSION,
        }

    def _tz(self) -> datetime.tzinfo:
        return dt_util.get_time_zone(self.coordinator.hass.config.time_zone) or dt_util.get_default_time_zone()

    def _raw_to_calendar_event(self, raw: dict[str, Any]) -> CalendarEvent | None:
        date_str = raw.get("date", "")
        start_min = int(raw.get("start_minutes", 0))
        end_min = int(raw.get("end_minutes", 0))
        try:
            d = datetime.strptime(date_str, "%d.%m.%Y").date()
        except ValueError:
            return None

        tz = self._tz()
        start_dt = datetime.combine(d, time(start_min // 60, start_min % 60), tzinfo=tz)
        end_dt = datetime.combine(d, time(end_min // 60, end_min % 60), tzinfo=tz)
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(minutes=45)

        teachers = ", ".join(raw.get("teachers", []))
        room = raw.get("room") or None

        return CalendarEvent(
            start=start_dt,
            end=end_dt,
            summary=raw.get("subject") or "Lesson",
            location=room,
            description=teachers or None,
            uid=f"wilma_{self._student_id}_{raw.get('id', '')}",
        )

    def _all_events(self) -> list[CalendarEvent]:
        if not self.coordinator.data:
            return []
        raw_list = self.coordinator.data.get("schedules", {}).get(self._student_id, [])
        events = []
        for raw in raw_list:
            evt = self._raw_to_calendar_event(raw)
            if evt:
                events.append(evt)
        return events

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming lesson (required by CalendarEntity)."""
        now = dt_util.now()
        upcoming = [e for e in self._all_events() if e.end > now]
        return min(upcoming, key=lambda e: e.start) if upcoming else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return all events within the requested date range."""
        raw_events = await self.coordinator.async_fetch_schedule_for_student_range(
            self._student_id,
            start_date,
            end_date,
        )
        return [
            e for raw in raw_events
            if (e := self._raw_to_calendar_event(raw))
            if e.start < end_date and e.end > start_date
        ]


class WilmaExamCalendarEntity(CoordinatorEntity, CalendarEntity):
    """Calendar entity with one student's upcoming exams as all-day events."""

    def __init__(
        self,
        coordinator: WilmaCoordinator,
        entry: ConfigEntry,
        student_id: str,
        student_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._student_id = student_id
        first_name = student_name.split()[0] if student_name else student_name
        self._attr_unique_id = f"{entry.entry_id}_{student_id}_exams_calendar"
        self._attr_has_entity_name = True
        self._attr_name = coordinator.entity_name("exams")
        self.internal_integration_suggested_object_id = coordinator.entity_object_id(
            "exams",
            student_name,
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_{student_id}")},
            "name": f"Wilma {first_name}",
            "manufacturer": "Visma",
            "model": "Wilma",
            "sw_version": INTEGRATION_VERSION,
        }

    def _all_events(self) -> list[CalendarEvent]:
        if not self.coordinator.data:
            return []
        events: list[CalendarEvent] = []
        for raw in self.coordinator.data.get("exams", {}).get(self._student_id, []):
            try:
                d = date.fromisoformat(raw.get("date", ""))
            except ValueError:
                continue
            subject = raw.get("subject") or "Koe"
            topic = raw.get("topic")
            description_parts = []
            if topic:
                description_parts.append(topic)
            if raw.get("info"):
                description_parts.append(raw["info"])
            if raw.get("teachers"):
                description_parts.append(", ".join(raw["teachers"]))
            events.append(
                CalendarEvent(
                    start=d,
                    end=d + timedelta(days=1),
                    summary=f"{subject}: {topic}" if topic else subject,
                    description="\n".join(description_parts) or None,
                    uid=f"wilma_exam_{self._student_id}_{raw.get('id', '')}",
                )
            )
        events.sort(key=lambda e: e.start)
        return events

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming exam."""
        today = dt_util.now().date()
        upcoming = [e for e in self._all_events() if e.end > today]
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return exams within the requested range."""
        tz = dt_util.get_time_zone(hass.config.time_zone) or dt_util.get_default_time_zone()
        return [
            e for e in self._all_events()
            if datetime.combine(e.start, time.min, tzinfo=tz) < end_date
            and datetime.combine(e.end, time.min, tzinfo=tz) > start_date
        ]
