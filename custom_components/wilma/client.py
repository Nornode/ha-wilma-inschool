"""Resilient WilmaClient wrapper for handling incomplete API payloads."""

from __future__ import annotations

import datetime
import logging
from typing import Any

from wilhelmina import Message, WilmaClient, WilmaError

_LOGGER = logging.getLogger(__name__)


def _sanitize_senders(raw_senders: Any) -> list[dict[str, Any]]:
    """Return a list of valid sender dicts compatible with wilhelmina.Sender."""
    if not isinstance(raw_senders, list):
        return []

    sanitized: list[dict[str, Any]] = []
    for entry in raw_senders:
        if not isinstance(entry, dict):
            continue
        name = entry.get("Name")
        if name is None:
            name = ""
        elif not isinstance(name, str):
            name = str(name)
        item = dict(entry)
        item["Name"] = name
        if "Href" in item and item["Href"] is not None and not isinstance(item["Href"], str):
            item["Href"] = str(item["Href"])
        sanitized.append(item)
    return sanitized


def normalize_message_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """Fill missing or null metadata fields in a raw Wilma message payload."""
    normalized = dict(raw)

    senders = _sanitize_senders(normalized.get("Senders"))
    normalized["Senders"] = senders

    if normalized.get("Subject") is None:
        normalized["Subject"] = ""
    elif not isinstance(normalized["Subject"], str):
        normalized["Subject"] = str(normalized["Subject"])

    if normalized.get("TimeStamp") is None:
        normalized["TimeStamp"] = ""
    elif not isinstance(normalized["TimeStamp"], str):
        normalized["TimeStamp"] = str(normalized["TimeStamp"])

    if normalized.get("Folder") is None:
        normalized["Folder"] = ""
    elif not isinstance(normalized["Folder"], str):
        normalized["Folder"] = str(normalized["Folder"])

    if normalized.get("SenderId") is None:
        normalized["SenderId"] = 0

    if normalized.get("SenderType") is None:
        normalized["SenderType"] = 0

    sender = normalized.get("Sender")
    if not sender:
        fallback_sender = next(
            (s["Name"] for s in senders if s.get("Name")),
            "",
        )
        normalized["Sender"] = fallback_sender
    elif not isinstance(sender, str):
        normalized["Sender"] = str(sender)

    if normalized.get("AllowForward") is None:
        normalized["AllowForward"] = True

    if normalized.get("AllowReply") is None:
        normalized["AllowReply"] = True

    if not isinstance(normalized.get("ReplyList"), list):
        normalized["ReplyList"] = []

    return normalized


class ResilientWilmaClient(WilmaClient):
    """WilmaClient subclass resilient to missing or null message fields."""

    async def get_messages(
        self,
        only_unread: bool = False,
        after: datetime.datetime | None = None,
        with_content: bool = False,
        no_message_content_fetch_limit: bool = False,
    ) -> list[Message]:
        """Get messages list while tolerating missing optional metadata fields."""
        unread_message_ids = await self._get_unread_message_ids()

        response = await self._authenticated_request("{user_id}/messages/list")
        data = await response.json()
        messages: list[Message] = []

        if after and after.tzinfo is not None:
            after = after.replace(tzinfo=None)

        raw_messages = data.get("Messages", []) if isinstance(data, dict) else []
        for raw_msg in raw_messages:
            if not isinstance(raw_msg, dict) or raw_msg.get("Id") is None:
                _LOGGER.warning("Skipping malformed Wilma message entry without Id: %r", raw_msg)
                continue

            try:
                message = Message.from_dict(normalize_message_dict(raw_msg))
            except Exception as err:
                _LOGGER.warning(
                    "Skipping unparseable Wilma message %s: %s",
                    raw_msg.get("Id"),
                    err,
                )
                continue

            message.unread = message.id in unread_message_ids

            if only_unread and not message.unread:
                continue

            if after and message.timestamp:
                try:
                    if message.format_timestamp() <= after:
                        continue
                except ValueError:
                    _LOGGER.debug(
                        "Message %s has unparseable timestamp %r; skipping 'after' filter",
                        message.id,
                        message.timestamp,
                    )

            messages.append(message)

        if with_content:
            if len(messages) > 10:
                if not no_message_content_fetch_limit:
                    raise WilmaError(
                        "Not allowed to fetch full message content for more than 10 messages."
                        "Set no_message_content_fetch_limit=True to override this limit."
                    )
                _LOGGER.warning(
                    "Fetching full message content for %s messages may take a while..",
                    len(messages),
                )
            for message in messages:
                try:
                    full_message = await self.get_message_content(message.id)
                    message.content_html = full_message.content_html
                    for attr, value in vars(full_message).items():
                        if attr != "unread" and getattr(message, attr, None) is None:
                            setattr(message, attr, value)
                except Exception as err:
                    _LOGGER.warning("Failed to fetch content for message %s: %s", message.id, err)

        return messages

    async def get_message_content(self, message_id: int) -> Message:
        """Get content of a message while tolerating missing metadata fields."""
        unread_message_ids = await self._get_unread_message_ids()

        url = f"{{user_id}}/messages/{message_id}"
        response = await self._authenticated_request(url, params={"format": "json"})

        data = await response.json()
        raw_messages = data.get("messages") if isinstance(data, dict) else None
        if not isinstance(raw_messages, list) or not raw_messages or not isinstance(raw_messages[0], dict):
            raise WilmaError(f"Message {message_id} response did not contain message data")

        message = Message.from_dict(normalize_message_dict(raw_messages[0]))
        message.unread = message_id in unread_message_ids
        return message
