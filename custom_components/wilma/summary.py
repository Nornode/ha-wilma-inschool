"""Persistent storage for AI-generated Wilma summaries."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    GENERATED_BY_AGENT,
    SIGNAL_SUMMARY_ADDED,
    SIGNAL_SUMMARY_UPDATED,
    STORAGE_VERSION,
    SUMMARY_HISTORY_LIMIT,
    SUMMARY_STORAGE_KEY,
)

_LOGGER = logging.getLogger(__name__)

_EMPTY_STATES = {"unknown", "unavailable", "none", ""}


def source_fingerprint(text: str | None) -> str | None:
    """Return a short stable hash of the summarised source text."""
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def compose_source_text(
    hass: HomeAssistant,
    source_entity: str | None,
    source_attribute: str | None = None,
) -> str:
    """Build the text to summarise from an entity state and optional attribute.

    Both the status service and the staleness check use this, so a summary is
    always compared against text assembled the same way it was generated.
    """
    if not source_entity:
        return ""

    state = hass.states.get(source_entity)
    if state is None:
        return ""

    state_text = "" if state.state.lower() in _EMPTY_STATES else state.state.strip()

    attribute_text = ""
    if source_attribute:
        value = state.attributes.get(source_attribute)
        if value is not None:
            attribute_text = str(value).strip()

    if state_text and attribute_text:
        return f"{state_text}\n\n{attribute_text}"

    return attribute_text or state_text


class WilmaSummaryStore:
    """Store AI summaries per student and summary key.

    The store is deliberately agnostic about how a summary was produced. It
    persists whatever text it is given plus the prompt metadata supplied by the
    caller, so summaries survive restarts and can be rendered in Lovelace.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the summary store."""
        self.hass = hass
        self.entry_id = entry_id
        self._store = Store(hass, STORAGE_VERSION, f"{SUMMARY_STORAGE_KEY}_{entry_id}")
        self._data: dict[str, dict[str, dict[str, Any]]] = {}

    async def async_load(self) -> None:
        """Load persisted summaries."""
        raw = await self._store.async_load() or {}
        students = raw.get("students")
        self._data = students if isinstance(students, dict) else {}

    async def _async_save(self) -> None:
        await self._store.async_save({"students": self._data})

    def stored_keys(self) -> list[tuple[str, str]]:
        """Return all (student_id, summary_key) pairs that have a summary."""
        return [
            (student_id, key)
            for student_id, entries in self._data.items()
            for key in entries
        ]

    def get(self, student_id: str, key: str) -> dict[str, Any] | None:
        """Return the stored summary record, if any."""
        return self._data.get(student_id, {}).get(key)

    async def async_store(
        self,
        student_id: str,
        student_name: str | None,
        key: str,
        summary: str,
        *,
        title: str | None = None,
        prompt: str | None = None,
        instructions: str | None = None,
        source_entity: str | None = None,
        source_attribute: str | None = None,
        source_id: str | None = None,
        source_text: str | None = None,
        agent_id: str | None = None,
        generated_by: str = GENERATED_BY_AGENT,
    ) -> dict[str, Any]:
        """Persist one summary and notify listeners."""
        entries = self._data.setdefault(student_id, {})
        previous = entries.get(key)
        is_new = previous is None

        record: dict[str, Any] = {
            "key": key,
            "student_id": student_id,
            "student_name": student_name,
            "summary": summary,
            "title": title,
            "prompt": prompt,
            "instructions": instructions,
            "source_entity": source_entity,
            "source_attribute": source_attribute,
            "source_id": source_id,
            "source_hash": source_fingerprint(source_text),
            "source_length": len(source_text) if source_text else 0,
            "agent_id": agent_id,
            "generated_by": generated_by,
            "generated_at": dt_util.utcnow().isoformat(),
            "last_error": None,
            "last_error_at": None,
            "error_count": 0,
        }

        history = list(previous.get("history", [])) if previous else []
        if previous:
            history.insert(
                0,
                {
                    "summary": previous.get("summary"),
                    "title": previous.get("title"),
                    "prompt": previous.get("prompt"),
                    "source_id": previous.get("source_id"),
                    "generated_by": previous.get("generated_by"),
                    "generated_at": previous.get("generated_at"),
                },
            )
        record["history"] = history[:SUMMARY_HISTORY_LIMIT]

        entries[key] = record
        await self._async_save()

        if is_new:
            async_dispatcher_send(
                self.hass,
                SIGNAL_SUMMARY_ADDED.format(self.entry_id),
                student_id,
                student_name,
                key,
            )
        else:
            async_dispatcher_send(
                self.hass,
                SIGNAL_SUMMARY_UPDATED.format(self.entry_id),
                student_id,
                key,
            )

        return record

    async def async_store_error(
        self,
        student_id: str,
        student_name: str | None,
        key: str,
        error: str,
    ) -> dict[str, Any]:
        """Record a failed generation attempt, keeping any existing summary."""
        entries = self._data.setdefault(student_id, {})
        record = entries.get(key)
        is_new = record is None

        if record is None:
            record = {
                "key": key,
                "student_id": student_id,
                "student_name": student_name,
                "summary": None,
                "history": [],
                "error_count": 0,
            }
            entries[key] = record

        record["last_error"] = error
        record["last_error_at"] = dt_util.utcnow().isoformat()
        record["error_count"] = int(record.get("error_count") or 0) + 1

        await self._async_save()

        if is_new:
            async_dispatcher_send(
                self.hass,
                SIGNAL_SUMMARY_ADDED.format(self.entry_id),
                student_id,
                student_name,
                key,
            )
        else:
            async_dispatcher_send(
                self.hass,
                SIGNAL_SUMMARY_UPDATED.format(self.entry_id),
                student_id,
                key,
            )

        return record

    async def async_clear(
        self,
        student_id: str | None = None,
        key: str | None = None,
    ) -> int:
        """Remove stored summaries and return how many records were removed."""
        removed = 0

        if student_id is None and key is not None:
            cleared = [
                (entry_student, key)
                for entry_student, entries in self._data.items()
                if key in entries
            ]
            for entry_student, _ in cleared:
                self._data[entry_student].pop(key)
            removed = len(cleared)
        elif student_id is None:
            removed = sum(len(entries) for entries in self._data.values())
            cleared = self.stored_keys()
            self._data = {}
        else:
            entries = self._data.get(student_id, {})
            if key is None:
                removed = len(entries)
                cleared = [(student_id, entry_key) for entry_key in entries]
                self._data.pop(student_id, None)
            elif key in entries:
                removed = 1
                cleared = [(student_id, key)]
                entries.pop(key)
            else:
                cleared = []

        if removed:
            await self._async_save()
            for cleared_student, cleared_key in cleared:
                async_dispatcher_send(
                    self.hass,
                    SIGNAL_SUMMARY_UPDATED.format(self.entry_id),
                    cleared_student,
                    cleared_key,
                )

        return removed
