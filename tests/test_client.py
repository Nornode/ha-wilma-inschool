"""Tests for the ResilientWilmaClient wrapper."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from custom_components.wilma.client import ResilientWilmaClient


def _make_json_response(payload: dict) -> MagicMock:
    """Create a mock aiohttp response returning the given JSON payload."""
    response = MagicMock()
    response.json = AsyncMock(return_value=payload)
    return response


async def test_get_messages_tolerates_missing_sender_id_and_metadata():
    """Verify messages missing SenderId/SenderType/Sender/Folder do not raise MissingField."""
    client = ResilientWilmaClient("https://vihti.inschool.fi")
    client.user_id = "!12345"
    client._sid = "sid"
    client._get_unread_message_ids = AsyncMock(return_value={101})
    client._authenticated_request = AsyncMock(
        return_value=_make_json_response(
            {
                "Messages": [
                    {
                        "Id": 101,
                        "Subject": "System notice",
                        "TimeStamp": "2026-11-20 12:00",
                        "Folder": "Inbox",
                        "SenderType": 1,
                        "Sender": "Wilma Admin",
                        # SenderId intentionally omitted (Issue #7)
                    },
                    {
                        "Id": 102,
                        "Subject": "Automated alert",
                        "TimeStamp": "2026-11-20 11:00",
                        "Senders": [{"Name": "System"}],
                        # SenderId, SenderType, Sender, Folder all omitted
                    },
                    {
                        "Id": 103,
                        "Subject": "Null fields",
                        "TimeStamp": "",
                        "Folder": None,
                        "SenderId": None,
                        "SenderType": None,
                        "Sender": None,
                    },
                    {
                        # Malformed entry without Id should be skipped
                        "Subject": "No ID",
                    },
                ]
            }
        )
    )

    messages = await client.get_messages(after=datetime(2026, 11, 20, 10, 0))

    assert [m.id for m in messages] == [101, 102, 103]
    assert messages[0].sender_id == 0
    assert messages[0].sender == "Wilma Admin"
    assert messages[0].unread is True

    assert messages[1].sender_id == 0
    assert messages[1].sender_type == 0
    assert messages[1].folder == ""
    assert messages[1].sender == "System"
    assert messages[1].unread is False

    assert messages[2].sender_id == 0
    assert messages[2].timestamp == ""


async def test_get_message_content_tolerates_missing_sender_id():
    """Verify full-message fetch also tolerates missing SenderId."""
    client = ResilientWilmaClient("https://vihti.inschool.fi")
    client.user_id = "!12345"
    client._sid = "sid"
    client._get_unread_message_ids = AsyncMock(return_value=set())
    client._authenticated_request = AsyncMock(
        return_value=_make_json_response(
            {
                "messages": [
                    {
                        "Id": 101,
                        "Subject": "System notice",
                        "TimeStamp": "2026-11-20 12:00",
                        "Folder": "Inbox",
                        "SenderType": 1,
                        "Sender": "Wilma Admin",
                        "ContentHtml": "<p>Hello from Vihti</p>",
                    }
                ]
            }
        )
    )

    message = await client.get_message_content(101)

    assert message.id == 101
    assert message.sender_id == 0
    assert message.content_html == "<p>Hello from Vihti</p>"
