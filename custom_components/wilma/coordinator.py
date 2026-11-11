"""DataUpdateCoordinator for the Wilma integration."""

import asyncio
import json
import logging
import re
import unicodedata
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Any

from bs4 import BeautifulSoup
import html2text
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.event import async_call_later
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
    EVENT_NEW_EXAM,
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
        self._login_lock = asyncio.Lock()
        self._retry_cancel = None
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
        """Append ?langid= (or &langid=) to a Wilma URL if not already present."""
        if not url:
            return url
        if "langid=" in url:
            return url
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
            next_exam = "Seuraava koe"
            exams_name = "Kokeet"
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
            next_exam = "Nästa prov"
            exams_name = "Prov"
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
            next_exam = "Next exam"
            exams_name = "Exams"

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
            "next_exam": next_exam,
            "exams": exams_name,
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
    def _unwrap_safelinks(text: str) -> str:
        """Unwrap Microsoft Outlook SafeLinks URLs to their original destinations."""
        if not text or "safelinks.protection.outlook.com" not in text:
            return text

        pattern = r"https?://[a-zA-Z0-9\.\-]*safelinks\.protection\.outlook\.com/\?url=([^&\s\)]+)[^\s\)]*"

        def _replace(match: re.Match) -> str:
            raw_url = match.group(1)
            try:
                return urllib.parse.unquote(raw_url)
            except Exception:
                return match.group(0)

        return re.sub(pattern, _replace, text)

    @staticmethod
    def _html_to_markdown(html: str) -> str:
        """Convert HTML to markdown for notification-friendly output."""
        converter = html2text.HTML2Text()
        converter.ignore_links = False
        converter.ignore_images = True
        converter.body_width = 0
        md = converter.handle(html).strip()
        md = WilmaCoordinator._unwrap_safelinks(md)
        # Remove Wilma printable version link if present
        md = re.sub(r"\[\s*Utskriftsvänlig version\s*\]\([^)]+\)", "", md, flags=re.IGNORECASE)
        # Collapse excessive newlines
        md = re.sub(r"\n{3,}", "\n\n", md)
        return md.strip()

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
        path = f"{student_id.lstrip('/')}/messages/{message.id}" if student_id else f"messages/{message.id}"
        msg_dict["web_url"] = self._url_with_lang(f"{self.server_url.rstrip('/')}/{path}")
        return msg_dict

    @staticmethod
    def _parse_news_html(
        html: str,
        student_id: str,
        student_name: str,
        server_url: str = "",
        language: int | None = None,
    ) -> list[dict[str, Any]]:
        """Parse the Wilma news page into serializable bulletin dicts."""
        soup = BeautifulSoup(html, "html.parser")
        items: list[dict[str, Any]] = []
        current_section = ""
        read_more_re = re.compile(
            r"^(läs\s+hela|lue\s+koko|read\s+more|mer\s+information|näytä\s+lisää|visa\s+mer)",
            re.I,
        )

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

            # If anchor text is a generic "Läs hela notisen" / "Read more", locate the container heading
            if read_more_re.search(title):
                container = element.find_parent(["div", "article", "section", "li", "td"])
                cand_heading = None
                if container:
                    cand_heading = container.find(["h1", "h2", "h3", "h4", "h5", "h6"])
                if cand_heading and cand_heading.get_text(strip=True):
                    cand_text = cand_heading.get_text(" ", strip=True)
                    if not read_more_re.search(cand_text):
                        title = cand_text
                elif current_section and not read_more_re.search(current_section):
                    title = current_section

            path = f"{student_id.lstrip('/')}/news/{news_id}" if student_id else f"news/{news_id}"
            raw_url = f"{server_url.rstrip('/')}/{path}" if server_url else f"/{path}"
            if language is not None and "langid=" not in raw_url:
                sep = "&" if "?" in raw_url else "?"
                web_url = f"{raw_url}{sep}langid={language}"
            else:
                web_url = raw_url

            items.append(
                {
                    "news_id": int(news_id),
                    "title": title,
                    "date": current_section,
                    "section": current_section,
                    "url": f"{student_id.rstrip('/')}/news/{news_id}",
                    "web_url": web_url,
                    "student_id": student_id,
                    "student_name": student_name,
                }
            )

        deduped: dict[int, dict[str, Any]] = {}
        for item in items:
            nid = item["news_id"]
            if nid in deduped:
                # If existing title is non-generic and new title is generic, keep existing
                if read_more_re.search(item["title"]) and not read_more_re.search(deduped[nid]["title"]):
                    continue
            deduped[nid] = item
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
            item["web_url"] = self._url_with_lang(full_url)
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

        # Decompose elements that are navigation, header, footer, cookies, or modal dialogues
        for tag in soup.find_all(
            ["nav", "header", "footer", "script", "style", "noscript", "iframe"]
        ):
            tag.decompose()
        for tag in soup.find_all(
            attrs={"role": ["navigation", "banner", "contentinfo", "dialog"]}
        ):
            tag.decompose()
        for tag in soup.find_all(
            class_=re.compile(
                r"(navbar|nav-container|site-header|site-footer|sidebar|breadcrumb|cookie|modal)",
                re.I,
            )
        ):
            tag.decompose()
        for tag in soup.find_all(
            id=re.compile(
                r"(navbar|site-header|site-footer|sidebar|breadcrumb|cookie|modal)",
                re.I,
            )
        ):
            tag.decompose()

        read_more_re = re.compile(
            r"^(läs\s+hela|lue\s+koko|read\s+more|mer\s+information|näytä\s+lisää|visa\s+mer)",
            re.I,
        )
        title = item.get("title") or ""
        heading = soup.find(["h1", "h2", "h3"])
        if heading and heading.get_text(" ", strip=True):
            cand = heading.get_text(" ", strip=True)
            if not read_more_re.search(cand):
                title = cand

        content_root = (
            soup.find("article")
            or soup.find("main")
            or soup.find(attrs={"role": "main"})
            or soup.find(id=re.compile(r"^(main-content|main|content)$", re.I))
            or soup.find(class_=re.compile(r"(main-content|inner-content|news-content|article-content)", re.I))
        )
        if not content_root and heading:
            content_root = heading.parent

        if not content_root:
            return item

        content_html = (
            content_root.decode_contents().strip()
            if hasattr(content_root, "decode_contents")
            else str(content_root).strip()
        )
        content_markdown = self._html_to_markdown(content_html)

        item.update(
            {
                "title": title,
                "content_html": content_html,
                "content_markdown": content_markdown,
            }
        )
        return item

    @staticmethod
    def _is_login_page(html: str) -> bool:
        """Return True if the HTML is the Wilma login form (silent session expiry)."""
        lower = html.lower()
        return "<form" in lower and 'type="password"' in lower

    async def _is_session_valid(self) -> bool:
        """Return False if the current session token is stale."""
        if not self.client:
            return False
        try:
            session = await self.client._ensure_session()
            headers = {"Wilma2SID": self.client._sid or ""}
            async with session.get(self.client.base_url, headers=headers) as resp:
                if resp.status != 200:
                    return False
                html = await resp.text()
                return not self._is_login_page(html)
        except Exception:
            return False

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

        if self._is_login_page(html):
            self.last_http_status = -1
            self.client = None
            _LOGGER.warning("Wilma session expired — login page returned; will re-authenticate on next cycle")
            return []

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

            if self._is_login_page(html):
                self.last_http_status = -1
                self.client = None
                raise UpdateFailed(f"Wilma session expired (login page on news fetch for {student_id})")

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
            return self._parse_news_html(html, student_id, student_name, self.server_url, self.language)
        except UpdateFailed:
            raise
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
        server_url: str = "",
        language: int | None = None,
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

        for msg in existing_by_id.values():
            if server_url and not msg.get("web_url") and msg.get("id"):
                sid = msg.get("student_id", "")
                path = f"{sid.lstrip('/')}/messages/{msg['id']}" if sid else f"messages/{msg['id']}"
                raw = f"{server_url.rstrip('/')}/{path}"
                sep = "&" if "?" in raw else "?"
                msg["web_url"] = f"{raw}{sep}langid={language}" if (language and "langid=" not in raw) else raw

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
        server_url: str = "",
        language: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Merge bulletin lists and deduplicate by news id."""
        existing_by_id = {
            item["news_id"]: item
            for item in existing_news
            if "news_id" in item
        }
        existing_ids = set(existing_by_id)
        read_more_re = re.compile(
            r"^(läs\s+hela|lue\s+koko|read\s+more|mer\s+information|näytä\s+lisää|visa\s+mer)",
            re.I,
        )

        for item in fetched_news:
            news_id = item.get("news_id")
            if news_id is None:
                continue
            if news_id in existing_by_id:
                prev = existing_by_id[news_id]
                for key in ("content_html", "content_markdown", "fetched_at"):
                    if prev.get(key) and not item.get(key):
                        item[key] = prev[key]
                if prev.get("title") and not read_more_re.search(prev["title"]) and (not item.get("title") or read_more_re.search(item.get("title", ""))):
                    item["title"] = prev["title"]
                elif prev.get("title") and not item.get("title"):
                    item["title"] = prev["title"]
            elif now_iso:
                item.setdefault("fetched_at", now_iso)
            existing_by_id[news_id] = item

        for item in existing_by_id.values():
            # If title is generic "Läs hela notisen", attempt recovery from heading/date/section
            if not item.get("title") or read_more_re.search(item["title"]):
                md = item.get("content_markdown") or ""
                m = re.search(r"^##?\s+(.+)$", md, re.MULTILINE)
                if m and not read_more_re.search(m.group(1).strip()):
                    item["title"] = m.group(1).strip()
                elif item.get("date") and not read_more_re.search(item["date"]):
                    item["title"] = item["date"]
                elif item.get("section") and not read_more_re.search(item["section"]):
                    item["title"] = item["section"]

            if server_url and not item.get("web_url") and item.get("news_id"):
                sid = item.get("student_id", "")
                path = f"{sid.lstrip('/')}/news/{item['news_id']}" if sid else f"news/{item['news_id']}"
                raw = f"{server_url.rstrip('/')}/{path}"
                sep = "&" if "?" in raw else "?"
                item["web_url"] = f"{raw}{sep}langid={language}" if (language and "langid=" not in raw) else raw
            elif language and item.get("web_url") and "langid=" not in item["web_url"]:
                sep = "&" if "?" in item["web_url"] else "?"
                item["web_url"] = f"{item['web_url']}{sep}langid={language}"

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

    async def _async_relogin(self, stale_client: Any) -> bool:
        """Replace a missing/invalidated Wilma session with a fresh login.

        Wilma allows only one active session per account: logging in elsewhere
        (browser, another script) makes the old Wilma2SID return HTTP 403.
        ``stale_client`` is the client that failed; if another task already
        replaced it, the new session is reused instead of logging in again
        (a second login would invalidate the first one).
        """
        async with self._login_lock:
            if self.client is not None and self.client is not stale_client:
                return True
            old, self.client = self.client, None
            if old is not None:
                try:
                    await old.close()
                except Exception as err:  # pragma: no cover
                    _LOGGER.debug("Error closing stale Wilma client: %s", err)
            client = WilmaClient(self.server_url)
            try:
                await client.login(self.username, self.password)
            except Exception as err:
                _LOGGER.warning("Wilma re-login failed: %s", err)
                self.last_fetch_errors.append(f"Re-login failed: {err}")
                try:
                    await client.close()
                except Exception:  # pragma: no cover
                    pass
                return False
            _LOGGER.info("Re-authenticated to Wilma (previous session was missing or invalidated)")
            self.client = client
            return True

    async def _fetch_schedule_for_student(
        self, student_id: str, for_date: date | None = None
    ) -> list[dict[str, Any]]:
        """Fetch one week of schedule for a student.

        On a missing or invalidated session (HTTP 401/403 or login page) the
        session is renewed once and the request retried.
        """
        student_name = next(
            (p["name"] for p in self.student_profiles if p["id"] == student_id),
            self.username,
        )
        path = f"{student_id.lstrip('/')}/schedule"
        if for_date:
            path += f"?date={for_date.strftime('%d.%m.%Y')}"
        url = self._url_with_lang(f"{self.server_url.rstrip('/')}/{path}")

        for attempt in range(2):
            client = self.client
            if client is None:
                if attempt or not await self._async_relogin(None):
                    _LOGGER.warning("Schedule fetch for %s: no Wilma session available", student_id)
                    return []
                continue
            try:
                session = await client._ensure_session()
                headers = {"Wilma2SID": client._sid or ""}
                _LOGGER.debug("Fetching schedule from: %s", url)
                async with session.get(url, headers=headers) as resp:
                    self.last_http_status = resp.status
                    status = resp.status
                    html = await resp.text() if status == 200 else ""
            except Exception as err:
                msg = f"Error fetching schedule for {student_id}: {err}"
                _LOGGER.error(msg, exc_info=True)
                self.last_fetch_errors.append(msg)
                return []

            session_lost = status in (401, 403) or (status == 200 and self._is_login_page(html))
            if session_lost:
                if attempt == 0:
                    _LOGGER.info(
                        "Schedule for %s returned %s (session invalidated); re-authenticating",
                        student_id,
                        "login page" if status == 200 else f"HTTP {status}",
                    )
                    if await self._async_relogin(client):
                        continue
                msg = f"Schedule for {student_id}: Wilma session could not be renewed (HTTP {status})"
                _LOGGER.warning(msg)
                self.last_fetch_errors.append(msg)
                return []

            if status != 200:
                msg = f"Schedule for {student_id} returned HTTP {status}"
                _LOGGER.warning(msg)
                self.last_fetch_errors.append(msg)
                return []

            schedule_heading = self._extract_page_heading(html)
            if schedule_heading:
                self.ui_labels["schedule"] = schedule_heading

            events = self._parse_schedule_html(html, student_id, student_name)
            _LOGGER.debug("Parsed %d schedule events for %s", len(events), student_id)
            return events
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
    def _parse_exams_html(
        html: str,
        student_id: str,
        student_name: str,
        server_url: str = "",
        language: int | None = None,
    ) -> list[dict[str, Any]]:
        """Parse upcoming exams from /exams/calendar.

        Each exam is rendered as its own ``table.table-grey``: the first row holds
        the date (``<strong>Ma 9.11.2026</strong>``) and ``"<topic> : <code> : <name>"``,
        followed by ``<th>label</th><td>value</td>`` detail rows (teacher, info...).
        """
        soup = BeautifulSoup(html, "html.parser")
        container = soup.find("main") or soup
        exams: list[dict[str, Any]] = []
        path = f"{student_id.lstrip('/')}/exams/calendar" if student_id else "exams/calendar"
        raw_url = f"{server_url.rstrip('/')}/{path}" if server_url else f"/{path}"
        if language is not None and "langid=" not in raw_url:
            sep = "&" if "?" in raw_url else "?"
            web_url = f"{raw_url}{sep}langid={language}"
        else:
            web_url = raw_url
        for table in container.select("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            first = rows[0]
            strong = first.find("strong")
            if not strong:
                continue
            date_match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", strong.get_text(" ", strip=True))
            if not date_match:
                continue
            day, month, year = (int(x) for x in date_match.groups())
            try:
                exam_date = date(year, month, day)
            except ValueError:
                continue

            cells = first.find_all("td")
            title_text = cells[-1].get_text(" ", strip=True) if len(cells) > 1 else ""
            title_text = re.sub(r"\s+", " ", title_text).strip()
            parts = [p.strip() for p in title_text.split(" : ")]
            parts = [p.rstrip(" :").strip() for p in parts if p.strip(" :")]
            topic = course_code = course_name = ""
            if len(parts) >= 3:
                topic = " : ".join(parts[:-2])
                course_code, course_name = parts[-2], parts[-1]
            elif len(parts) == 2:
                course_code, course_name = parts
            elif parts:
                course_name = parts[0]

            teachers: list[str] = []
            info = ""
            details: dict[str, str] = {}
            for row in rows[1:]:
                th, td = row.find("th"), row.find("td")
                if not th or not td:
                    continue
                label = th.get_text(" ", strip=True)
                links = td.select("a.ope, a[href*='/profiles/teachers/']")
                if links:
                    teachers = [a.get_text(" ", strip=True) for a in links]
                    details[label] = ", ".join(teachers)
                    continue
                value = re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip()
                if not value:
                    continue
                details[label] = value
                if "lisätied" in label.lower() or "additional" in label.lower() or "tilläggs" in label.lower():
                    info = value

            subject = course_name or course_code
            exam_id = f"{exam_date.isoformat()}_{course_code or course_name or topic}"
            exams.append({
                "id": exam_id,
                "date": exam_date.isoformat(),
                "subject": subject,
                "course_code": course_code,
                "course_name": course_name,
                "topic": topic,
                "info": info,
                "teachers": teachers,
                "details": details,
                "student_id": student_id,
                "student_name": student_name,
                "web_url": web_url,
            })

        exams.sort(key=lambda e: (e["date"], e["subject"]))
        return exams

    async def _fetch_exams_for_student(self, student_id: str) -> list[dict[str, Any]] | None:
        """Fetch upcoming exams for a student. Returns None on failure."""
        if not self.client:
            return None
        student_name = next(
            (p["name"] for p in self.student_profiles if p["id"] == student_id),
            self.username,
        )
        try:
            session = await self.client._ensure_session()
            headers = {"Wilma2SID": self.client._sid or ""}
            url = f"{self.server_url.rstrip('/')}/{student_id.lstrip('/')}/exams/calendar"
            async with session.get(self._url_with_lang(url), headers=headers) as resp:
                self.last_http_status = resp.status
                if resp.status != 200:
                    msg = f"Exams for {student_id} returned HTTP {resp.status}"
                    _LOGGER.warning(msg)
                    self.last_fetch_errors.append(msg)
                    return None
                html = await resp.text()

            if self._is_login_page(html):
                self.last_http_status = -1
                self.client = None
                raise UpdateFailed(f"Wilma session expired (login page on exams fetch for {student_id})")

            exams_heading = self._extract_page_heading(html)
            if exams_heading:
                self.ui_labels["exams"] = exams_heading

            exams = self._parse_exams_html(html, student_id, student_name, self.server_url, self.language)
            _LOGGER.debug("Parsed %d exams for %s", len(exams), student_id)
            return exams
        except UpdateFailed:
            raise
        except Exception as err:
            msg = f"Error fetching exams for {student_id}: {err}"
            _LOGGER.error(msg, exc_info=True)
            self.last_fetch_errors.append(msg)
            return None

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

                    # A teacher's note puts free text where the mark type name
                    # normally is; keep it instead of losing it to the legend label.
                    note = ""
                    if legend_name and mark_type_name != legend_name:
                        text = mark_type_name.replace("\r\n", "\n").strip()
                        if not any(
                            text == label or text.endswith(f"({label})")
                            for label in legend.values()
                        ):
                            note = text

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
                        "note": note,
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
            now = dt_util.now()
            start_year = now.year if now.month >= 8 else now.year - 1
            end_year = start_year + 1

            # Full history view for current school year (1 Aug - 31 Jul)
            view_url = f"{base}/{uid}/attendance/view?range=-3&first=01.08.{start_year}&last=31.07.{end_year}"
            async with session.get(self._url_with_lang(view_url), headers=h) as resp:
                self.last_http_status = resp.status
                if resp.status != 200:
                    self.last_fetch_errors.append(
                        f"Attendance view for {student_id} returned HTTP {resp.status}"
                    )
                    return None, None
                view_html = await resp.text()

            if view_html and self._is_login_page(view_html):
                self.last_http_status = -1
                self.client = None
                raise UpdateFailed(f"Wilma session expired (login page on attendance fetch for {student_id})")

            # Unexplained marks
            unexplained_url = f"{base}/{uid}/attendance"
            async with session.get(self._url_with_lang(unexplained_url), headers=h) as resp:
                self.last_http_status = resp.status
                if resp.status == 200:
                    unexplained_html = await resp.text()
                else:
                    self.last_fetch_errors.append(
                        f"Attendance unexplained for {student_id} returned HTTP {resp.status}"
                    )
                    unexplained_html = ""

            attendance_heading = self._extract_page_heading(unexplained_html)
            if attendance_heading:
                self.ui_labels["attendance"] = attendance_heading

            all_marks = self._parse_attendance_view_html(view_html)
            unexplained = self._parse_attendance_unexplained_html(unexplained_html) if unexplained_html else []
            return all_marks, unexplained
        except UpdateFailed:
            raise
        except Exception as err:
            _LOGGER.debug("Error fetching attendance for %s: %s", student_id, err)
            self.last_fetch_errors.append(f"Attendance fetch for {student_id} failed: {err}")
            return None, None

    async def _async_update_data(self):
        """Fetch data from Wilma."""
        self.last_fetch_errors = []
        data = await self.store.async_load() or {}
        stored_students = data.get("students", {})
        stored_news = data.get("news", {})
        stored_attendance = data.get("attendance", {})
        stored_exams = data.get("exams", {})
        if not isinstance(stored_exams, dict):
            stored_exams = {}
        if not isinstance(stored_students, dict):
            stored_students = {}
        if not isinstance(stored_news, dict):
            stored_news = {}
        if not isinstance(stored_attendance, dict):
            stored_attendance = {}

        try:
            if self.client is not None and not await self._is_session_valid():
                _LOGGER.warning("Wilma session no longer valid; re-authenticating")
                await self.async_close_client()

            if self.client is None:
                self.client = WilmaClient(self.server_url)
                _LOGGER.debug(
                    f"Connecting to Wilma server {self.server_url} as {self.username}"
                )
                await self.client.login(self.username, self.password)

            self.student_profiles = await self._discover_students()
            if not self.student_profiles and self.client is not None and self.client.user_id:
                self.student_profiles = [{"id": self.client.user_id, "name": self.username}]
            if not self.student_profiles:
                self.client = None
                raise UpdateFailed("No student profiles found — possible session expiry")

            updated_students: dict[str, list[dict[str, Any]]] = {}
            updated_news: dict[str, list[dict[str, Any]]] = {}
            new_bulletins_by_student: dict[str, list[dict[str, Any]]] = {}

            pending_message_events: list[dict[str, Any]] = []
            pending_bulletin_events: list[dict[str, Any]] = []

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
                    after_timestamp = dt_util.now().replace(tzinfo=None) - timedelta(days=7)

                fetched_messages = await self._fetch_messages_for_student(student_id, after_timestamp)
                merged_messages, new_messages = self._merge_messages(
                    existing_messages,
                    fetched_messages,
                    self.server_url,
                    self.language,
                )
                updated_students[student_id] = merged_messages

                if new_messages and existing_messages:
                    for message in new_messages:
                        pending_message_events.append(
                            {
                                "entry_id": self.entry_id,
                                "student_id": student_id,
                                "student_name": student["name"],
                                "message_id": message.get("id"),
                                "subject": message.get("subject"),
                                "sender": message.get("sender"),
                                "timestamp": message.get("timestamp"),
                                "unread": message.get("unread"),
                                "content": message.get("content_markdown") or message.get("content_html"),
                                "content_html": message.get("content_html"),
                                "content_markdown": message.get("content_markdown"),
                            }
                        )

                fetched_news = await self._fetch_news_for_student(student_id)
                merged_news, new_news = self._merge_news(
                    existing_news,
                    fetched_news,
                    dt_util.utcnow().isoformat(),
                    self.server_url,
                    self.language,
                )
                new_bulletins_by_student[student_id] = new_news

                if merged_news:
                    if not merged_news[0].get("content_markdown"):
                        merged_news[0] = await self._fetch_news_body(student_id, merged_news[0])

                if new_news and existing_news:
                    for i, item in enumerate(new_news):
                        item = await self._fetch_news_body(student_id, item)
                        new_news[i] = item
                        for j, m_item in enumerate(merged_news):
                            if m_item.get("news_id") == item.get("news_id"):
                                merged_news[j] = item
                                break
                        pending_bulletin_events.append(
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
                            }
                        )

                updated_news[student_id] = merged_news

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
            attendance: dict[str, list[dict[str, Any]]] = {}
            unexplained: dict[str, list[dict[str, Any]]] = {}
            pending_attendance_events: list[dict[str, Any]] = []

            for student in self.student_profiles:
                student_id = student["id"]
                fetched_marks, fetched_unexplained = await self._fetch_attendance_for_student(student_id)

                prev_student_marks = (
                    (self.data or {}).get("attendance", {}).get(student_id)
                    or stored_attendance.get(student_id, [])
                )
                prev_unexplained = (
                    (self.data or {}).get("unexplained_attendance", {}).get(student_id)
                    or []
                )

                if fetched_marks is None:
                    # Fetch failed; preserve existing attendance data to avoid wiping baseline
                    attendance[student_id] = prev_student_marks
                    unexplained[student_id] = prev_unexplained
                    continue

                attendance[student_id] = fetched_marks
                unexplained[student_id] = (
                    fetched_unexplained if fetched_unexplained is not None else prev_unexplained
                )

                # Baseline check: only fire events if this student already had a baseline
                has_baseline = (
                    student_id in stored_attendance
                    or (self.data is not None and student_id in self.data.get("attendance", {}))
                )

                if has_baseline:
                    prev_ids = {
                        m["_id"]
                        for m in prev_student_marks
                        if isinstance(m, dict) and "_id" in m
                    }
                    for mark in fetched_marks:
                        mark_id = mark.get("_id", "")
                        if mark_id and mark_id not in prev_ids:
                            pending_attendance_events.append(
                                {
                                    "entry_id": self.entry_id,
                                    "student_id": student_id,
                                    "student_name": student.get("name", ""),
                                    "mark": {k: v for k, v in mark.items() if not k.startswith("_")},
                                }
                            )

            # Fetch upcoming exams for each student
            exams: dict[str, list[dict[str, Any]]] = {}
            pending_exam_events: list[dict[str, Any]] = []
            for student in self.student_profiles:
                student_id = student["id"]
                prev_exams = (
                    (self.data or {}).get("exams", {}).get(student_id)
                    or stored_exams.get(student_id, [])
                )
                fetched_exams = await self._fetch_exams_for_student(student_id)
                if fetched_exams is None:
                    exams[student_id] = prev_exams
                    continue
                exams[student_id] = fetched_exams

                has_baseline = student_id in stored_exams or (
                    self.data is not None and student_id in self.data.get("exams", {})
                )
                if has_baseline:
                    prev_ids = {e.get("id") for e in prev_exams if isinstance(e, dict)}
                    for exam in fetched_exams:
                        if exam["id"] not in prev_ids:
                            pending_exam_events.append(
                                {
                                    "entry_id": self.entry_id,
                                    "student_id": student_id,
                                    "student_name": student.get("name", ""),
                                    **{k: v for k, v in exam.items() if k not in ("student_id", "student_name")},
                                }
                            )

            # Persist merged storage across cycles BEFORE firing events
            await self.store.async_save(
                {
                    "students": {**stored_students, **updated_students},
                    "news": {**stored_news, **updated_news},
                    "attendance": {**stored_attendance, **attendance},
                    "exams": {**stored_exams, **exams},
                }
            )

            # Fire events only after persistent store has been committed
            for msg_event in pending_message_events:
                self.hass.bus.async_fire(EVENT_NEW_MESSAGE, msg_event)

            for bulletin_event in pending_bulletin_events:
                self.hass.bus.async_fire(EVENT_NEW_BULLETIN, bulletin_event)

            for attendance_event in pending_attendance_events:
                self.hass.bus.async_fire(EVENT_NEW_ATTENDANCE, attendance_event)

            for exam_event in pending_exam_events:
                self.hass.bus.async_fire(EVENT_NEW_EXAM, exam_event)

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
                student_id: len(new_bulletins_by_student.get(student_id, []))
                for student_id in {p["id"] for p in self.student_profiles}
            }

            all_messages = [
                message
                for student_messages in updated_students.values()
                for message in student_messages
            ]
            all_messages.sort(key=self._timestamp_sort_key, reverse=True)

            # Reset retry delay on successful cycle
            self._auth_retry_delay = 60

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
                "exams": exams,
            }

        except AuthenticationError as err:
            self.client = None
            if _is_server_auth_rejection(err):
                _LOGGER.error(
                    "Wilma rejected token creation (HTTP 403). Credentials may be valid but login flow was rejected: %s",
                    err,
                )
                raise UpdateFailed("Authentication rejected by Wilma server (HTTP 403)") from err

            err_str = str(err)
            is_transient = any(code in err_str for code in ("502", "503", "504"))
            retry_delay = getattr(self, "_auth_retry_delay", 60)

            if is_transient:
                _LOGGER.warning(
                    "Authentication to Wilma failed (server unavailable: %s). Retrying in %ds",
                    err,
                    retry_delay,
                )
                self._auth_retry_delay = min(retry_delay * 2, 300)
            else:
                _LOGGER.error("Authentication to Wilma failed: %s", err)
                self._auth_retry_delay = 60

            if self._retry_cancel:
                self._retry_cancel()
            self._retry_cancel = async_call_later(
                self.hass, retry_delay, self._async_retry_refresh
            )
            raise UpdateFailed("Authentication failed") from err
        except WilmaError as err:
            _LOGGER.error("Error communicating with Wilma: %s", err)
            raise UpdateFailed(f"Error communicating with Wilma: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error updating from Wilma: %s", err)
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def _async_retry_refresh(self, _now: Any = None) -> None:
        """Retry refresh after transient authentication failure."""
        await self.async_request_refresh()

    async def async_close_client(self):
        """Close the Wilma client."""
        if self._retry_cancel:
            self._retry_cancel()
            self._retry_cancel = None
        if self.client:
            try:
                await self.client.close()
            except Exception as err:
                _LOGGER.error("Error closing Wilma client: %s", err)
            finally:
                self.client = None
