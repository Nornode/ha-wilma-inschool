"""Calendar platform for Wilma integration — one calendar per student."""

from __future__ import annotations

import logging
import zoneinfo
from datetime import datetime, time, timedelta
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

    async_add_entities(
        WilmaCalendarEntity(coordinator, entry, p["id"], p["name"]) for p in profiles
    )


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
        self._attr_translation_key = "schedule"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{entry.entry_id}_{student_id}")},
            "name": f"Wilma {first_name}",
            "manufacturer": "Visma",
            "model": "Wilma",
            "sw_version": INTEGRATION_VERSION,
        }

    def _tz(self) -> zoneinfo.ZoneInfo:
        return zoneinfo.ZoneInfo(self.coordinator.hass.config.time_zone)

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
        return [
            e for e in self._all_events()
            if e.start < end_date and e.end > start_date
        ]
