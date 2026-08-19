"""DataUpdateCoordinator for the Wilma integration."""

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from bs4 import BeautifulSoup
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from wilhelmina import AuthenticationError, Message, Sender, WilmaClient, WilmaError

from .const import (
    CONF_NO_MESSAGE_CONTENT_FETCH_LIMIT,
    CONF_ONLY_UNREAD,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DEFAULT_NO_MESSAGE_CONTENT_FETCH_LIMIT,
    DEFAULT_ONLY_UNREAD,
    DOMAIN,
    EVENT_NEW_MESSAGE,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


class WilmaCoordinator(DataUpdateCoordinator):
    """Coordinator for fetching data from Wilma."""

    def __init__(
        self,
        hass: HomeAssistant,
        server_url: str,
        username: str,
        password: str,
        entry_id: str,
        options: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the coordinator."""
        self.options = options or {}
        update_interval = timedelta(
            minutes=int(
                self.options.get(
                    CONF_SCAN_INTERVAL_MINUTES,
                    DEFAULT_SCAN_INTERVAL_MINUTES,
                )
            )
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval or DEFAULT_SCAN_INTERVAL,
        )
        self.server_url = server_url
        self.username = username
        self.password = password
        self.entry_id = entry_id
        self.client = None
        self.store = Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}_{entry_id}")
        self.last_update_success_time = None
        self.student_profiles: list[dict[str, str]] = []

    @property
    def only_unread(self) -> bool:
        """Return whether to fetch only unread messages."""
        return bool(self.options.get(CONF_ONLY_UNREAD, DEFAULT_ONLY_UNREAD))

    @property
    def no_message_content_fetch_limit(self) -> bool:
        """Return whether content fetch limit is disabled."""
        return bool(
            self.options.get(
                CONF_NO_MESSAGE_CONTENT_FETCH_LIMIT,
                DEFAULT_NO_MESSAGE_CONTENT_FETCH_LIMIT,
            )
        )

    @staticmethod
    def _timestamp_sort_key(message: dict[str, Any]) -> datetime:
        """Build a sort key from a stored message dict."""
        timestamp = message.get("timestamp")
        if not isinstance(timestamp, str):
            return datetime.min

        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                parsed = datetime.strptime(timestamp, fmt)
                return parsed.replace(tzinfo=None)
            except ValueError:
                continue
        return datetime.min

    @staticmethod
    def _serialize_senders(senders: list[Sender]) -> list[dict[str, str | None]]:
        """Serialize sender objects for Home Assistant storage."""
        serialized: list[dict[str, str | None]] = []
        for sender in senders:
            serialized.append({"name": sender.name, "href": sender.href})
        return serialized

    def _message_to_dict(self, message: Message, student_id: str, student_name: str) -> dict[str, Any]:
        """Convert a Wilhelmina message object into a serializable dict."""
        msg_dict: dict[str, Any] = {
            "id": message.id,
            "subject": message.subject,
            "timestamp": message.timestamp,
            "folder": message.folder,
            "sender_id": message.sender_id,
            "sender_type": message.sender_type,
            "sender": message.sender,
            "allow_forward": message.allow_forward,
            "allow_reply": message.allow_reply,
            "reply_list": message.reply_list,
            "senders": self._serialize_senders(message.senders),
            "unread": message.unread,
            "content_html": message.content_html,
            "student_id": student_id,
            "student_name": student_name,
        }
        if message.content_html:
            try:
                msg_dict["content_markdown"] = message.content_markdown
            except ValueError:
                pass
        return msg_dict

    async def _discover_students(self) -> list[dict[str, str]]:
        """Discover available user IDs from the authenticated home page."""
        if not self.client:
            return []

        default_id = self.client.user_id or ""
        student_map: dict[str, str] = {}
        if default_id:
            student_map[default_id] = self.username

        try:
            session = await self.client._ensure_session()
            headers = {"Wilma2SID": self.client._sid or ""}
            async with session.get(self.client.base_url, headers=headers) as response:
                if response.status != 200:
                    return [{"id": default_id, "name": self.username}] if default_id else []

                html = await response.text()
        except Exception as err:  # pragma: no cover - network issues are environment-specific
            _LOGGER.debug("Could not discover student IDs from home page: %s", err)
            return [{"id": default_id, "name": self.username}] if default_id else []

        soup = BeautifulSoup(html, "html.parser")
        for link in soup.select("a[href]"):
            href = link.get("href") or ""
            match = re.search(r"/(![A-Za-z0-9]+)", href)
            if not match:
                continue
            student_id = match.group(1)
            text = link.get_text(" ", strip=True)
            if student_id in student_map:
                # Replace fallback username with discovered profile name when available.
                if text and student_map[student_id] == self.username:
                    student_map[student_id] = text
                continue

            student_map[student_id] = text if text else f"Student {student_id}"

        if not student_map and default_id:
            student_map[default_id] = self.username

        return [
            {"id": student_id, "name": name}
            for student_id, name in sorted(student_map.items(), key=lambda item: item[0])
        ]

    async def _fetch_messages_for_student(
        self,
        student_id: str,
        after_timestamp: datetime | None,
    ) -> list[dict[str, Any]]:
        """Fetch messages for one student user ID."""
        if not self.client:
            return []

        original_user_id = self.client.user_id
        self.client.user_id = student_id
        try:
            messages = await self.client.get_messages(
                only_unread=self.only_unread,
                with_content=True,
                after=after_timestamp,
                no_message_content_fetch_limit=self.no_message_content_fetch_limit,
            )
        finally:
            self.client.user_id = original_user_id

        student_name = next(
            (
                profile["name"]
                for profile in self.student_profiles
                if profile["id"] == student_id
            ),
            self.username,
        )
        return [self._message_to_dict(message, student_id, student_name) for message in messages]

    @staticmethod
    def _merge_messages(
        existing_messages: list[dict[str, Any]],
        fetched_messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Merge message lists and deduplicate by message id."""
        existing_by_id = {
            message["id"]: message
            for message in existing_messages
            if "id" in message
        }
        existing_ids = set(existing_by_id)

        for message in fetched_messages:
            message_id = message.get("id")
            if message_id is None:
                continue
            existing_by_id[message_id] = message

        merged = sorted(
            existing_by_id.values(),
            key=WilmaCoordinator._timestamp_sort_key,
            reverse=True,
        )
        new_messages = [
            message for message in fetched_messages if message.get("id") not in existing_ids
        ]
        new_messages.sort(key=WilmaCoordinator._timestamp_sort_key, reverse=True)

        return merged, new_messages

    async def _async_update_data(self):
        """Fetch data from Wilma."""
        data = await self.store.async_load() or {}
        stored_students = data.get("students", {})
        if not isinstance(stored_students, dict):
            stored_students = {}

        try:
            if self.client is None:
                self.client = WilmaClient(
                    self.server_url,
                    session=async_get_clientsession(self.hass),
                )
                _LOGGER.debug(
                    f"Connecting to Wilma server {self.server_url} as {self.username}"
                )
                await self.client.login(self.username, self.password)

            self.student_profiles = await self._discover_students()
            if not self.student_profiles and self.client.user_id:
                self.student_profiles = [{"id": self.client.user_id, "name": self.username}]

            updated_students: dict[str, list[dict[str, Any]]] = {}

            for student in self.student_profiles:
                student_id = student["id"]
                existing_messages = stored_students.get(student_id, [])

                after_timestamp = None
                if existing_messages and isinstance(existing_messages[0].get("timestamp"), str):
                    try:
                        after_timestamp = datetime.strptime(
                            existing_messages[0]["timestamp"],
                            "%Y-%m-%d %H:%M",
                        )
                    except ValueError:
                        after_timestamp = None
                if after_timestamp is None:
                    after_timestamp = dt_util.utcnow().replace(tzinfo=None) - timedelta(days=7)

                fetched_messages = await self._fetch_messages_for_student(student_id, after_timestamp)
                merged_messages, new_messages = self._merge_messages(
                    existing_messages,
                    fetched_messages,
                )
                updated_students[student_id] = merged_messages

                if new_messages and existing_messages:
                    for message in new_messages:
                        self.hass.bus.async_fire(
                            EVENT_NEW_MESSAGE,
                            {
                                "entry_id": self.entry_id,
                                "student_id": student_id,
                                "student_name": student["name"],
                                "message_id": message.get("id"),
                                "subject": message.get("subject"),
                                "sender": message.get("sender"),
                                "timestamp": message.get("timestamp"),
                                "unread": message.get("unread"),
                            },
                        )

            await self.store.async_save({"students": updated_students})

            # Update last successful update time
            self.last_update_success_time = dt_util.utcnow()

            latest_message_by_student = {
                student_id: messages[0] if messages else None
                for student_id, messages in updated_students.items()
            }
            unread_count_by_student = {
                student_id: sum(1 for message in messages if message.get("unread"))
                for student_id, messages in updated_students.items()
            }

            all_messages = [
                message
                for student_messages in updated_students.values()
                for message in student_messages
            ]
            all_messages.sort(key=self._timestamp_sort_key, reverse=True)

            return {
                "students": updated_students,
                "student_profiles": self.student_profiles,
                "messages": all_messages,
                "latest_message": all_messages[0] if all_messages else None,
                "latest_message_by_student": latest_message_by_student,
                "unread_count": sum(unread_count_by_student.values()),
                "unread_count_by_student": unread_count_by_student,
                "last_update": dt_util.as_local(self.last_update_success_time),
            }

        except AuthenticationError as err:
            self.client = None
            _LOGGER.error("Authentication to Wilma failed: %s", err)
            raise UpdateFailed("Authentication failed") from err
        except WilmaError as err:
            _LOGGER.error("Error communicating with Wilma: %s", err)
            raise UpdateFailed(f"Error communicating with Wilma: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error updating from Wilma: %s", err)
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def async_close_client(self):
        """Close the Wilma client."""
        if self.client:
            try:
                await self.client.close()
            except Exception as err:
                _LOGGER.error("Error closing Wilma client: %s", err)
            finally:
                self.client = None
