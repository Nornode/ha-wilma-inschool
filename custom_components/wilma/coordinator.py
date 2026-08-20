"""DataUpdateCoordinator for the Wilma integration."""

import json
import logging
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any

from bs4 import BeautifulSoup
import html2text
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from wilhelmina import AuthenticationError, Message, Sender, WilmaClient, WilmaError

from .const import (
    CONF_LANGUAGE,
    CONF_NO_MESSAGE_CONTENT_FETCH_LIMIT,
    CONF_ONLY_UNREAD,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_LANGUAGE,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DEFAULT_NO_MESSAGE_CONTENT_FETCH_LIMIT,
    DEFAULT_ONLY_UNREAD,
    DOMAIN,
    EVENT_NEW_BULLETIN,
    EVENT_NEW_ATTENDANCE,
    EVENT_NEW_MESSAGE,
    SCHEDULE_WEEKS_AHEAD,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


def _is_server_auth_rejection(err: AuthenticationError) -> bool:
    """Return true when Wilma rejects token minting with HTTP 403."""
    err_text = str(err).lower()
    return "403" in err_text and "token" in err_text


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
        self.ui_labels: dict[str, str] = {}
        self.last_fetch_errors: list[str] = []
        self.last_http_status: int | None = None

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

    @property
    def language(self) -> int:
        """Return the configured langid for Wilma requests."""
        return int(self.options.get(CONF_LANGUAGE, DEFAULT_LANGUAGE))

    def _url_with_lang(self, url: str) -> str:
        """Append ?langid= (or &langid=) to a Wilma URL."""
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}langid={self.language}"

    def _translation_placeholders_for_key(self, entity_key: str) -> dict[str, str]:
        """Return placeholder values used by translated entity names."""
        message_singular, message_plural = self._noun_forms_for_label(
            self.ui_labels.get("message", "Message")
        )
        bulletin_singular, bulletin_plural = self._noun_forms_for_label(
            self.ui_labels.get("bulletin", "Bulletin")
        )
        schedule_singular, schedule_plural = self._noun_forms_for_label(
            self.ui_labels.get("schedule", "Schedule")
        )
        attendance_singular, attendance_plural = self._noun_forms_for_label(
            self.ui_labels.get("attendance", "Attendance")
        )

        if entity_key in {"latest_message", "unread_count", "recent_message"}:
            return {
                "message_label_singular": message_singular,
                "message_label_plural": message_plural,
            }
        if entity_key in {"latest_bulletin", "unread_bulletin_count", "recent_bulletin"}:
            return {
                "bulletin_label_singular": bulletin_singular,
                "bulletin_label_plural": bulletin_plural,
            }
        if entity_key in {"next_lesson", "schedule"}:
            return {
                "schedule_label_singular": schedule_singular,
                "schedule_label_plural": schedule_plural,
            }
        if entity_key in {"attendance_count", "latest_attendance", "recent_attendance"}:
            return {
                "attendance_label_singular": attendance_singular,
                "attendance_label_plural": attendance_plural,
            }
        return {}

    def entity_name(self, entity_key: str) -> str:
        """Return a localized friendly entity name independent of HA UI language."""
        if self.language == 1:
            message_singular, message_plural = "viesti", "viestit"
        elif self.language == 2:
            message_singular, message_plural = "meddelande", "meddelanden"
        else:
            message_singular, message_plural = "message", "messages"

        bulletin_singular, bulletin_plural = self._noun_forms_for_label(
            self.ui_labels.get("bulletin", "Bulletin")
        )

        if self.language == 1:
            latest_prefix = "Viimeisin"
            unread_prefix = "Lukemattomat"
            last_update = "Viimeisin päivitys"
            problem = "Ongelma"
            http_status = "Viimeisin HTTP-tila"
            schedule_name = self.ui_labels.get("schedule", "Opiskelijan työjärjestys")
            next_lesson = "Seuraava tunti"
            bulletin_latest = f"{latest_prefix} {bulletin_singular}"
            bulletin_unread = f"{unread_prefix} {bulletin_plural}"
            message_latest = f"{latest_prefix} {message_singular}"
            message_unread = f"{unread_prefix} {message_plural}"
            attendance_latest = f"{latest_prefix} tuntimerkintä"
            attendance_count = "tuntimerkinnät"
        elif self.language == 2:
            latest_prefix = "Senaste"
            unread_prefix = "Olästa"
            last_update = "Senaste uppdatering"
            problem = "Problem"
            http_status = "Senaste HTTP-status"
            schedule_name = self.ui_labels.get("schedule", "Studerandens schema")
            next_lesson = "Nästa lektion"
            bulletin_latest = f"{latest_prefix} {bulletin_singular}"
            bulletin_unread = f"{unread_prefix} {bulletin_plural}"
            message_latest = f"{latest_prefix} {message_singular}"
            message_unread = f"{unread_prefix} {message_plural}"
            attendance_latest = f"{latest_prefix} lektionsanteckning"
            attendance_count = "lektionsanteckningar"
        else:
            latest_prefix = "Latest"
            unread_prefix = "Unread"
            last_update = "Last update"
            problem = "Problem"
            http_status = "Last HTTP status"
            schedule_name = self.ui_labels.get("schedule", "Schedule")
            next_lesson = "Next lesson"
            bulletin_latest = f"{latest_prefix} {bulletin_singular}"
            bulletin_unread = f"{unread_prefix} {bulletin_plural}"
            message_latest = f"{latest_prefix} {message_singular}"
            message_unread = f"{unread_prefix} {message_plural}"
            attendance_latest = f"{latest_prefix} attendance mark"
            attendance_count = "attendance marks"

        mapping = {
            "problem": problem,
            "recent_message": message_latest,
            "latest_message": message_latest,
            "unread_count": message_unread,
            "recent_bulletin": bulletin_latest,
            "latest_bulletin": bulletin_latest,
            "unread_bulletin_count": bulletin_unread,
            "recent_attendance": attendance_latest,
            "last_update": last_update,
            "next_lesson": next_lesson,
            "attendance_count": attendance_count,
            "latest_attendance": attendance_latest,
            "last_http_status": http_status,
            "schedule": schedule_name,
        }

        return mapping.get(entity_key, entity_key)

    @staticmethod
    def _slugify_object_id(text: str) -> str:
        """Return an English, ASCII-safe object-id slug."""
        first_token = text.split()[0] if text.split() else text
        normalized = unicodedata.normalize("NFKD", first_token)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_text).strip("_").lower()
        return slug or "wilma"

    def entity_object_id(
        self,
        entity_key: str,
        student_name: str | None = None,
    ) -> str:
        """Return the stable English object id for one entity."""
        if student_name:
            student_slug = self._slugify_object_id(student_name)
            return f"wilma_{student_slug}_{entity_key}"

        return f"wilma_{entity_key}"

    @staticmethod
    def _noun_forms_for_label(label: str) -> tuple[str, str]:
        """Return singular and plural noun forms derived from a scraped UI label."""
        if not label:
            return "", ""

        noun = label.split()[-1]
        lowered = noun.lower()
        singular_map = {
            "meddelanden": "meddelande",
            "notiser": "notis",
            "anteckningar": "anteckning",
            "viestit": "viesti",
            "tiedotteet": "tiedote",
            "tuntimerkinnät": "tuntimerkning",
        }
        plural_map = {
            "meddelanden": "meddelanden",
            "notiser": "notiser",
            "anteckningar": "anteckningar",
            "viestit": "viestit",
            "tiedotteet": "tiedotteet",
            "tuntimerkinnät": "tuntimerkningar",
        }

        singular = singular_map.get(lowered, noun)
        plural = plural_map.get(lowered, noun)
        return singular, plural

    @staticmethod
    def _extract_ui_labels(home_html: str) -> dict[str, str]:
        """Extract localized Wilma navigation labels from the authenticated home page."""
        soup = BeautifulSoup(home_html, "html.parser")
        labels: dict[str, str] = {}

        mapping = {
            "messages": "message",
            "news": "bulletin",
            "schedule": "schedule",
            "attendance": "attendance",
        }

        for link in soup.select("a[href]"):
            href = (link.get("href") or "").lower()
            text = link.get_text(" ", strip=True)
            if not text:
                continue

            # Ignore profile-scoped links such as /!123456/messages.
            if re.search(r"/![a-z0-9]+/", href):
                continue

            for path_part, key in mapping.items():
                if f"/{path_part}" in href:
                    labels.setdefault(key, text)

        return labels

    @staticmethod
    def _extract_page_heading(html: str) -> str | None:
        """Return the localized page label from the document title or heading."""
        soup = BeautifulSoup(html, "html.parser")
        if soup.title:
            title = soup.title.get_text(" ", strip=True)
            if title:
                if " - " in title:
                    title = title.rsplit(" - ", 1)[0].strip()
                if title:
                    return title

        for selector in ("h1", "main h2", "h2"):
            node = soup.select_one(selector)
            if node:
                text = node.get_text(" ", strip=True)
                if text:
                    return text
        return None

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

    @staticmethod
    def _news_sort_key(news_item: dict[str, Any]) -> tuple[int, int]:
        news_id = news_item.get("news_id")
        try:
            return (0, int(news_id))
        except (TypeError, ValueError):
            return (1, 0)

    @staticmethod
    def _html_to_markdown(html: str) -> str:
        """Convert HTML to markdown for notification-friendly output."""
        converter = html2text.HTML2Text()
        converter.ignore_links = False
        converter.ignore_images = True
        converter.body_width = 0
        return converter.handle(html).strip()

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

    @staticmethod
    def _parse_news_html(html: str, student_id: str, student_name: str) -> list[dict[str, Any]]:
        """Parse the Wilma news page into serializable bulletin dicts."""
        soup = BeautifulSoup(html, "html.parser")
        items: list[dict[str, Any]] = []
        current_section = ""
        for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "a"]):
            if element.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                current_section = element.get_text(" ", strip=True)
                continue

            href = element.get("href") or ""
            match = re.search(rf"/{re.escape(student_id.lstrip('/'))}/news/(\d+)", href)
            if not match:
                continue

            news_id = match.group(1)
            title = element.get_text(" ", strip=True)
            if not title:
                continue

            items.append(
                {
                    "news_id": int(news_id),
                    "title": title,
                    "date": current_section,
                    "section": current_section,
                    "url": f"{student_id.rstrip('/')}/news/{news_id}",
                    "student_id": student_id,
                    "student_name": student_name,
                }
            )

        deduped: dict[int, dict[str, Any]] = {}
        for item in items:
            deduped[item["news_id"]] = item
        return sorted(deduped.values(), key=WilmaCoordinator._news_sort_key)

    async def _fetch_news_body(self, student_id: str, news_item: dict[str, Any]) -> dict[str, Any]:
        """Fetch and attach article body for a single bulletin."""
        if not self.client:
            return news_item

        item = dict(news_item)
        url = item.get("url")
        if not url:
            return item

        original_user_id = self.client.user_id
        self.client.user_id = student_id
        try:
            session = await self.client._ensure_session()
            headers = {"Wilma2SID": self.client._sid or ""}
            full_url = f"{self.server_url.rstrip('/')}/{str(url).lstrip('/')}"
            async with session.get(self._url_with_lang(full_url), headers=headers) as resp:
                self.last_http_status = resp.status
                if resp.status != 200:
                    self.last_fetch_errors.append(
                        f"News article for {student_id} returned HTTP {resp.status}"
                    )
                    return item
                html = await resp.text()
        except Exception as err:
            _LOGGER.debug("Error fetching news article for %s: %s", student_id, err)
            self.last_fetch_errors.append(f"News article fetch for {student_id} failed: {err}")
            return item
        finally:
            self.client.user_id = original_user_id

        soup = BeautifulSoup(html, "html.parser")
        title = item.get("title") or ""
        heading = soup.find(["h1", "h2", "h3"])
        if heading and heading.get_text(" ", strip=True):
            title = heading.get_text(" ", strip=True)

        content_root = soup.find("article") or soup.body or soup
        content_html = content_root.decode_contents().strip() if hasattr(content_root, "decode_contents") else html.strip()
        content_markdown = self._html_to_markdown(content_html)

        item.update(
            {
                "title": title,
                "content_html": content_html,
                "content_markdown": content_markdown,
            }
        )
        return item

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
            async with session.get(self._url_with_lang(self.client.base_url), headers=headers) as response:
                self.last_http_status = response.status
                if response.status != 200:
                    self.last_fetch_errors.append(
                        f"Home page returned HTTP {response.status}"
                    )
                    return [{"id": default_id, "name": self.username}] if default_id else []

                html = await response.text()
        except Exception as err:  # pragma: no cover - network issues are environment-specific
            _LOGGER.debug("Could not discover student IDs from home page: %s", err)
            self.last_fetch_errors.append(f"Student discovery failed: {err}")
            return [{"id": default_id, "name": self.username}] if default_id else []

        soup = BeautifulSoup(html, "html.parser")
        self.ui_labels = self._extract_ui_labels(html)
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
            try:
                session = await self.client._ensure_session()
                headers = {"Wilma2SID": self.client._sid or ""}
                msg_url = f"{self.server_url.rstrip('/')}/{student_id.lstrip('/')}/messages"
                async with session.get(self._url_with_lang(msg_url), headers=headers) as resp:
                    self.last_http_status = resp.status
                    if resp.status == 200:
                        msg_html = await resp.text()
                        message_heading = self._extract_page_heading(msg_html)
                        if message_heading:
                            self.ui_labels["message"] = message_heading
            except Exception as err:
                _LOGGER.debug("Could not extract messages heading for %s: %s", student_id, err)

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

    async def _fetch_news_for_student(self, student_id: str) -> list[dict[str, Any]]:
        """Fetch news items for one student user ID."""
        if not self.client:
            return []

        original_user_id = self.client.user_id
        self.client.user_id = student_id
        try:
            session = await self.client._ensure_session()
            headers = {"Wilma2SID": self.client._sid or ""}
            url = f"{self.server_url.rstrip('/')}/{student_id.lstrip('/')}/news"
            async with session.get(self._url_with_lang(url), headers=headers) as resp:
                self.last_http_status = resp.status
                if resp.status != 200:
                    self.last_fetch_errors.append(
                        f"News for {student_id} returned HTTP {resp.status}"
                    )
                    return []
                html = await resp.text()

            news_heading = self._extract_page_heading(html)
            if news_heading:
                self.ui_labels["bulletin"] = news_heading

            student_name = next(
                (
                    profile["name"]
                    for profile in self.student_profiles
                    if profile["id"] == student_id
                ),
                self.username,
            )
            return self._parse_news_html(html, student_id, student_name)
        except Exception as err:
            _LOGGER.debug("Error fetching news for %s: %s", student_id, err)
            self.last_fetch_errors.append(f"News fetch for {student_id} failed: {err}")
            return []
        finally:
            self.client.user_id = original_user_id

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

    @staticmethod
    def _merge_news(
        existing_news: list[dict[str, Any]],
        fetched_news: list[dict[str, Any]],
        now_iso: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Merge bulletin lists and deduplicate by news id."""
        existing_by_id = {
            item["news_id"]: item
            for item in existing_news
            if "news_id" in item
        }
        existing_ids = set(existing_by_id)

        for item in fetched_news:
            news_id = item.get("news_id")
            if news_id is None:
                continue
            if news_id not in existing_ids and now_iso:
                item.setdefault("fetched_at", now_iso)
            existing_by_id[news_id] = item

        merged = sorted(existing_by_id.values(), key=WilmaCoordinator._news_sort_key, reverse=True)
        new_items = [item for item in fetched_news if item.get("news_id") not in existing_ids]
        new_items.sort(key=WilmaCoordinator._news_sort_key, reverse=True)
        return merged, new_items

    @staticmethod
    def _parse_schedule_html(
        html: str, student_id: str, student_name: str
    ) -> list[dict[str, Any]]:
        """Extract and parse eventsJSON from a schedule page."""
        m = re.search(r"var\s+eventsJSON\s*=\s*(\{.+\})\s*;", html, re.DOTALL)
        if not m:
            return []
        raw = m.group(1)
        # Convert JS object literal unquoted keys to JSON.
        # The pattern matches either a complete quoted string (to leave it alone)
        # or an unquoted identifier followed by ':' (to quote the key).
        _KEY_RE = re.compile(r'("(?:[^"\\]|\\.)*")|(?<!["\w])([A-Za-z_]\w*)\s*:')

        def _fix_key(match: re.Match) -> str:
            if match.group(1):
                return match.group(1)  # already-quoted string — return as-is
            return f'"{match.group(2)}":'

        raw_json = _KEY_RE.sub(_fix_key, raw)
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as err:
            _LOGGER.debug("Failed to parse schedule eventsJSON for %s: %s", student_id, err)
            return []

        events: list[dict[str, Any]] = []
        for raw_event in data.get("Events", []):
            try:
                text_obj = raw_event.get("Text") or {}
                subject = text_obj.get("0", "") if isinstance(text_obj, dict) else ""
                long_text_obj = raw_event.get("LongText") or {}
                subject_long = long_text_obj.get("0", "") if isinstance(long_text_obj, dict) else ""

                rooms_obj = raw_event.get("Huoneet") or {}
                room_raw = rooms_obj.get("0", "") if isinstance(rooms_obj, dict) else ""
                room = room_raw.removeprefix("H: ").strip() if room_raw else ""

                # Teacher names from first occurrence group in OpeInfo
                ope_info = raw_event.get("OpeInfo") or {}
                first_occ = ope_info.get("0", {}) if isinstance(ope_info, dict) else {}
                teachers = [
                    td["nimi"]
                    for td in (first_occ.values() if isinstance(first_occ, dict) else [])
                    if isinstance(td, dict) and td.get("nimi")
                ]

                # Create a unique ID by combining event ID, date, and start time
                # to avoid conflicts when same lesson appears on different dates
                event_date = raw_event.get("Date", "")
                event_id = str(raw_event.get("Id", ""))
                start_minutes = int(raw_event.get("Start", 0))
                unique_id = f"{event_id}_{event_date}_{start_minutes}"

                events.append({
                    "id": unique_id,
                    "date": event_date,
                    "start_minutes": start_minutes,
                    "end_minutes": int(raw_event.get("End", 0)),
                    "subject": subject,
                    "subject_long": subject_long,
                    "room": room,
                    "teachers": teachers,
                    "color": raw_event.get("Color", ""),
                    "type": raw_event.get("Tyyppi", ""),
                    "student_id": student_id,
                    "student_name": student_name,
                })
            except (KeyError, TypeError, ValueError) as err:
                _LOGGER.debug("Error parsing schedule event: %s", err)

        return events

    async def _fetch_schedule_for_student(
        self, student_id: str, for_date: date | None = None
    ) -> list[dict[str, Any]]:
        """Fetch one week of schedule for a student."""
        if not self.client:
            _LOGGER.warning("_fetch_schedule_for_student: no client available")
            return []
        student_name = next(
            (p["name"] for p in self.student_profiles if p["id"] == student_id),
            self.username,
        )
        try:
            session = await self.client._ensure_session()
            headers = {"Wilma2SID": self.client._sid or ""}
            path = f"{student_id.lstrip('/')}/schedule"
            if for_date:
                path += f"?date={for_date.strftime('%d.%m.%Y')}"
            url = f"{self.server_url.rstrip('/')}/{path}"
            _LOGGER.debug("Fetching schedule from: %s", url)
            async with session.get(self._url_with_lang(url), headers=headers) as resp:
                self.last_http_status = resp.status
                if resp.status != 200:
                    msg = f"Schedule for {student_id} returned HTTP {resp.status}"
                    _LOGGER.warning(msg)
                    self.last_fetch_errors.append(msg)
                    return []
                html = await resp.text()

            schedule_heading = self._extract_page_heading(html)
            if schedule_heading:
                self.ui_labels["schedule"] = schedule_heading

            events = self._parse_schedule_html(html, student_id, student_name)
            _LOGGER.debug("Parsed %d schedule events for %s", len(events), student_id)
            return events
        except Exception as err:
            msg = f"Error fetching schedule for {student_id}: {err}"
            _LOGGER.error(msg, exc_info=True)
            self.last_fetch_errors.append(msg)
            return []

    @staticmethod
    def _schedule_sort_key(evt: dict[str, Any]) -> tuple:
        date_str = evt.get("date", "")
        try:
            d = datetime.strptime(date_str, "%d.%m.%Y").date()
        except ValueError:
            d = date.min
        return (d, evt.get("start_minutes", 0))

    async def async_fetch_schedule_for_student_range(
        self,
        student_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[dict[str, Any]]:
        """Fetch schedule events for a student in the requested calendar range."""
        if end_date <= start_date:
            return []

        first_day = start_date.date()
        last_day = end_date.date()
        if end_date.time() == datetime.min.time():
            last_day -= timedelta(days=1)

        first_week = first_day - timedelta(days=first_day.weekday())
        last_week = last_day - timedelta(days=last_day.weekday())

        seen_ids: dict[str, dict[str, Any]] = {}
        week_date = first_week
        while week_date <= last_week:
            for evt in await self._fetch_schedule_for_student(student_id, week_date):
                seen_ids[evt["id"]] = evt
            week_date += timedelta(weeks=1)

        return sorted(seen_ids.values(), key=self._schedule_sort_key)

    @staticmethod
    def _parse_attendance_view_html(html: str) -> list[dict[str, Any]]:
        """Parse the full attendance history from /attendance/view.

        Extracts per-lesson marks with date, hour, subject, mark type and teacher
        from the grid table's cell title attributes and the legend table.
        """
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            return []

        # Build CSS-class → mark-type-name lookup from legend (second table)
        legend: dict[str, str] = {}
        if len(tables) >= 2:
            for row in tables[1].find_all("tr"):
                cells = row.find_all("td")
                if len(cells) >= 2:
                    css_classes = cells[0].get("class", [])
                    label = cells[1].get_text(strip=True)
                    for cls in css_classes:
                        if cls.startswith("at-tp"):
                            legend[cls] = label

        # Parse the grid table header to map column index → lesson hour
        grid = tables[0]
        header_row = grid.find("tr")
        if not header_row:
            return []

        # Build col_index → hour, accounting for colspan
        col_to_hour: list[str] = []
        for th in header_row.find_all("th"):
            text = th.get_text(strip=True)
            span = int(th.get("colspan", 1))
            col_to_hour.extend([text] * span)

        # col 0 = day-name (part of "Päivämäärä"), col 1 = date
        marks: list[dict[str, Any]] = []
        for row in grid.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue

            day = cells[0].get_text(strip=True) if len(cells) > 0 else ""
            date_str = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            if not date_str:
                continue

            # Walk remaining cells, tracking column position
            col_idx = 2  # first two cols consumed by day+date
            for cell in cells[2:]:
                span = int(cell.get("colspan", 1))
                css_classes = cell.get("class", [])
                title = cell.get("title", "")

                if "event" in css_classes and title:
                    # title format: "{SubjectCode}; {MarkTypeName} /{TeacherName}"
                    mark_type_name = ""
                    subject_code = ""
                    teacher = ""
                    parts = title.split(";", 1)
                    if parts:
                        subject_code = parts[0].strip()
                    if len(parts) > 1:
                        rest = parts[1].strip()
                        if "/" in rest:
                            type_part, teacher = rest.rsplit("/", 1)
                            mark_type_name = type_part.strip()
                        else:
                            mark_type_name = rest

                    # Resolve mark type from legend CSS class
                    legend_name = next(
                        (legend[c] for c in css_classes if c in legend), mark_type_name
                    )

                    # Determine lesson hour from column index
                    hour = col_to_hour[col_idx] if col_idx < len(col_to_hour) else ""

                    mark_id = f"{date_str}|{hour}|{subject_code}"
                    marks.append({
                        "date": date_str,
                        "day": day,
                        "lesson_hour": hour,
                        "subject_code": subject_code,
                        "mark_type": legend_name or mark_type_name,
                        "teacher": teacher.strip(),
                        "teacher_initials": cell.get_text(strip=True),
                        "_id": mark_id,
                    })

                col_idx += span

        # Return newest first (rows are newest-first in Wilma HTML)
        return marks

    @staticmethod
    def _parse_attendance_unexplained_html(html: str) -> list[dict[str, Any]]:
        """Parse marks that still need explanation from the plain /attendance page."""
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if not table:
            return []
        header_row = table.find("tr")
        if not header_row:
            return []
        headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
        marks: list[dict[str, Any]] = []
        for row in table.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            mark: dict[str, Any] = {}
            for i, cell in enumerate(cells):
                key = headers[i] if i < len(headers) else f"col_{i}"
                link = cell.find("a")
                mark[key] = cell.get_text(strip=True)
                if link and link.get("href"):
                    mark[f"{key}_href"] = link["href"]
            raw_id = "|".join(str(mark.get(h, "")) for h in headers[:4])
            mark["_id"] = raw_id
            marks.append(mark)
        return marks

    async def _fetch_attendance_for_student(
        self, student_id: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Return (all_marks, unexplained_marks) for one student."""
        if not self.client:
            return [], []
        try:
            session = await self.client._ensure_session()
            h = {"Wilma2SID": self.client._sid or ""}
            base = self.server_url.rstrip("/")
            uid = student_id.lstrip("/")
            year = dt_util.now().year

            # Full history view
            view_url = f"{base}/{uid}/attendance/view?range=-3&first=01.01.{year}&last=31.12.{year}"
            async with session.get(self._url_with_lang(view_url), headers=h) as resp:
                self.last_http_status = resp.status
                view_html = await resp.text() if resp.status == 200 else ""

            # Unexplained marks
            unexplained_url = f"{base}/{uid}/attendance"
            async with session.get(self._url_with_lang(unexplained_url), headers=h) as resp:
                self.last_http_status = resp.status
                unexplained_html = await resp.text() if resp.status == 200 else ""

            attendance_heading = self._extract_page_heading(unexplained_html)
            if attendance_heading:
                self.ui_labels["attendance"] = attendance_heading

            all_marks = self._parse_attendance_view_html(view_html) if view_html else []
            unexplained = self._parse_attendance_unexplained_html(unexplained_html) if unexplained_html else []
            return all_marks, unexplained
        except Exception as err:
            _LOGGER.debug("Error fetching attendance for %s: %s", student_id, err)
            return [], []

    async def _async_update_data(self):
        """Fetch data from Wilma."""
        self.last_fetch_errors = []
        data = await self.store.async_load() or {}
        stored_students = data.get("students", {})
        stored_news = data.get("news", {})
        if not isinstance(stored_students, dict):
            stored_students = {}
        if not isinstance(stored_news, dict):
            stored_news = {}

        try:
            if self.client is None:
                self.client = WilmaClient(self.server_url)
                _LOGGER.debug(
                    f"Connecting to Wilma server {self.server_url} as {self.username}"
                )
                await self.client.login(self.username, self.password)

            self.student_profiles = await self._discover_students()
            if not self.student_profiles and self.client.user_id:
                self.student_profiles = [{"id": self.client.user_id, "name": self.username}]

            updated_students: dict[str, list[dict[str, Any]]] = {}
            updated_news: dict[str, list[dict[str, Any]]] = {}

            for student in self.student_profiles:
                student_id = student["id"]
                existing_messages = stored_students.get(student_id, [])
                existing_news = stored_news.get(student_id, [])

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

                fetched_news = await self._fetch_news_for_student(student_id)
                merged_news, new_news = self._merge_news(existing_news, fetched_news, dt_util.utcnow().isoformat())

                if merged_news:
                    merged_news[0] = await self._fetch_news_body(student_id, merged_news[0])

                updated_news[student_id] = merged_news

                if new_news and existing_news:
                    for item in new_news:
                        item = await self._fetch_news_body(student_id, item)
                        self.hass.bus.async_fire(
                            EVENT_NEW_BULLETIN,
                            {
                                "entry_id": self.entry_id,
                                "student_id": student_id,
                                "student_name": student["name"],
                                "news_id": item.get("news_id"),
                                "title": item.get("title"),
                                "date": item.get("date"),
                                "section": item.get("section"),
                                "url": item.get("url"),
                                "content_html": item.get("content_html"),
                                "content_markdown": item.get("content_markdown"),
                            },
                        )

            await self.store.async_save({"students": updated_students, "news": updated_news})

            # Fetch schedules for the current week and upcoming weeks for each student.
            today = dt_util.now().date()
            current_week = today - timedelta(days=today.weekday())
            week_dates = [current_week + timedelta(weeks=i) for i in range(SCHEDULE_WEEKS_AHEAD)]
            _LOGGER.info(
                "Fetching schedules: today=%s, current_week=%s, weeks=%s",
                today,
                current_week,
                week_dates,
            )
            schedules: dict[str, list[dict[str, Any]]] = {}
            for student in self.student_profiles:
                student_id = student["id"]
                seen_ids: dict[str, dict[str, Any]] = {}
                for week_date in week_dates:
                    events = await self._fetch_schedule_for_student(student_id, week_date)
                    _LOGGER.info(
                        "Fetched %d events for %s on week %s",
                        len(events),
                        student_id,
                        week_date,
                    )
                    for evt in events:
                        seen_ids[evt["id"]] = evt
                schedules[student_id] = sorted(seen_ids.values(), key=self._schedule_sort_key)
                _LOGGER.info("Total unique events for %s: %d", student_id, len(schedules[student_id]))

            # Fetch attendance marks for each student
            prev_attendance: dict[str, set[str]] = {
                p["id"]: set(
                    m["_id"]
                    for m in (self.data or {}).get("attendance", {}).get(p["id"], [])
                )
                for p in self.student_profiles
            }
            attendance: dict[str, list[dict[str, Any]]] = {}
            unexplained: dict[str, list[dict[str, Any]]] = {}
            for student in self.student_profiles:
                student_id = student["id"]
                all_marks, unexplained_marks = await self._fetch_attendance_for_student(student_id)
                attendance[student_id] = all_marks
                unexplained[student_id] = unexplained_marks
                # Fire event for each new mark in the full history
                for mark in all_marks:
                    mark_id = mark.get("_id", "")
                    if mark_id and mark_id not in prev_attendance.get(student_id, set()):
                        self.hass.bus.async_fire(
                            EVENT_NEW_ATTENDANCE,
                            {
                                "student_id": student_id,
                                "student_name": student.get("name", ""),
                                "mark": {k: v for k, v in mark.items() if not k.startswith("_")},
                            },
                        )

            # Update last successful update time
            self.last_update_success_time = dt_util.utcnow()

            latest_message_by_student = {
                student_id: messages[0] if messages else None
                for student_id, messages in updated_students.items()
            }
            latest_bulletin_by_student = {
                student_id: news_items[0] if news_items else None
                for student_id, news_items in updated_news.items()
            }
            unread_count_by_student = {
                student_id: sum(1 for message in messages if message.get("unread"))
                for student_id, messages in updated_students.items()
            }
            unread_bulletin_count_by_student = {
                student_id: max(len(updated_news.get(student_id, [])) - len(stored_news.get(student_id, [])), 0)
                for student_id in {p["id"] for p in self.student_profiles}
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
                "news": updated_news,
                "latest_bulletin_by_student": latest_bulletin_by_student,
                "unread_bulletin_count_by_student": unread_bulletin_count_by_student,
                "last_update": dt_util.as_local(self.last_update_success_time),
                "schedules": schedules,
                "attendance": attendance,
                "unexplained_attendance": unexplained,
            }

        except AuthenticationError as err:
            self.client = None
            if _is_server_auth_rejection(err):
                _LOGGER.error(
                    "Wilma rejected token creation (HTTP 403). Credentials may be valid but login flow was rejected: %s",
                    err,
                )
                raise UpdateFailed("Authentication rejected by Wilma server (HTTP 403)") from err

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
