"""Test the Wilma data update coordinator."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from wilhelmina import AuthenticationError, WilmaError

from custom_components.wilma.coordinator import WilmaCoordinator


async def test_coordinator_update(hass, mock_wilma_client):
    """Test successful coordinator update."""
    # Create coordinator
    coordinator = WilmaCoordinator(
        hass, "https://test.inschool.fi", "testuser", "testpass", "test_entry_id"
    )

    # Test update
    data = await coordinator._async_update_data()

    # Verify results
    assert "messages" in data
    assert len(data["messages"]) == 3

    assert data["latest_message"]["id"] == 11
    assert data["latest_message"]["subject"] == "Test Message 11"
    assert data["unread_count"] == 2
    assert data["unread_count_by_student"]["!STUDENT1"] == 1
    assert data["unread_count_by_student"]["!STUDENT2"] == 1
    assert data["news"]["!STUDENT1"][0]["news_id"] == 101
    assert data["news"]["!STUDENT1"][0]["title"] == "Kid One latest bulletin"
    assert "Brand new" not in data["news"]["!STUDENT1"][0].get("content_markdown", "")
    assert "Line one for kid one." in data["news"]["!STUDENT1"][0].get("content_markdown", "")
    assert data["latest_bulletin_by_student"]["!STUDENT1"]["news_id"] == 101
    assert data["unread_bulletin_count_by_student"]["!STUDENT1"] == 2

    assert "last_update" in data

    # Verify client was initialized and called properly
    assert coordinator.client is not None
    mock_wilma_client.login.assert_called_once_with("testuser", "testpass")
    assert mock_wilma_client.get_messages.call_count == 2


async def test_coordinator_fires_new_bulletin_event_on_refresh(hass, mock_wilma_client):
        """Test new bulletin events are emitted when a new item appears."""
        coordinator = WilmaCoordinator(
                hass, "https://test.inschool.fi", "testuser", "testpass", "test_entry_id"
        )

        await coordinator._async_update_data()

        events: list[dict] = []

        def _capture(event):
                events.append(event.data)

        hass.bus.async_listen("wilma_new_bulletin", _capture)

        from tests.conftest import MOCK_NEWS_PAGES

        original_news_page = MOCK_NEWS_PAGES["!STUDENT1"]

        try:
                MOCK_NEWS_PAGES["!STUDENT1"] = """
                <html>
                    <body>
                        <h2>Tänään</h2>
                        <ul>
                            <li><a href="/!STUDENT1/news/102">Kid One brand new bulletin</a></li>
                            <li><a href="/!STUDENT1/news/101">Kid One latest bulletin</a></li>
                        </ul>
                    </body>
                </html>
                """

                await coordinator._async_update_data()
                await hass.async_block_till_done()

                assert any(event.get("news_id") == 102 for event in events)
                assert any("Brand new bulletin body." in event.get("content_markdown", "") for event in events)
        finally:
                MOCK_NEWS_PAGES["!STUDENT1"] = original_news_page


async def test_coordinator_auth_error(hass):
    """Test authentication error handling in coordinator."""
    client = MagicMock()
    client.login = AsyncMock(side_effect=AuthenticationError("Auth failed"))

    with patch("custom_components.wilma.coordinator.WilmaClient", return_value=client):
        # Create coordinator
        coordinator = WilmaCoordinator(
            hass, "https://test.inschool.fi", "testuser", "testpass", "test_entry_id"
        )

        # Test update with auth error
        with pytest.raises(UpdateFailed, match="Authentication failed"):
            await coordinator._async_update_data()

        # Verify client was cleared
        assert coordinator.client is None


async def test_coordinator_wilma_error(hass):
    """Test general Wilma error handling in coordinator."""
    client = MagicMock()
    client.login = AsyncMock()
    client.get_messages = AsyncMock(side_effect=WilmaError("API Error"))

    with patch("custom_components.wilma.coordinator.WilmaClient", return_value=client):
        # Create coordinator
        coordinator = WilmaCoordinator(
            hass, "https://test.inschool.fi", "testuser", "testpass", "test_entry_id"
        )

        # Test update with API error
        with pytest.raises(UpdateFailed, match="Error communicating with Wilma"):
            await coordinator._async_update_data()


async def test_coordinator_close(hass, mock_wilma_client):
    """Test the coordinator's close method."""
    # Create coordinator
    coordinator = WilmaCoordinator(
        hass, "https://test.inschool.fi", "testuser", "testpass", "test_entry_id"
    )

    # Update to initialize client
    await coordinator._async_update_data()
    assert coordinator.client is not None

    # Close client
    await coordinator.async_close_client()

    # Verify client was closed and reset
    mock_wilma_client.close.assert_called_once()
    assert coordinator.client is None


async def test_coordinator_fetch_schedule_range_uses_requested_window(hass):
    """Test schedule range fetching covers the requested calendar window."""
    coordinator = WilmaCoordinator(
        hass, "https://test.inschool.fi", "testuser", "testpass", "test_entry_id"
    )

    schedule_by_week = {
        date(2024, 5, 13): [
            {"id": "late", "date": "20.05.2024", "start_minutes": 600},
            {"id": "early", "date": "15.05.2024", "start_minutes": 480},
        ],
        date(2024, 5, 20): [
            {"id": "late", "date": "20.05.2024", "start_minutes": 600},
            {"id": "middle", "date": "17.05.2024", "start_minutes": 540},
        ],
    }

    async def _fetch_schedule(student_id, for_date):
        assert student_id == "!STUDENT1"
        return schedule_by_week[for_date]

    coordinator._fetch_schedule_for_student = AsyncMock(side_effect=_fetch_schedule)

    events = await coordinator.async_fetch_schedule_for_student_range(
        "!STUDENT1",
        datetime(2024, 5, 15, tzinfo=ZoneInfo("Europe/Helsinki")),
        datetime(2024, 5, 27, tzinfo=ZoneInfo("Europe/Helsinki")),
    )

    assert coordinator._fetch_schedule_for_student.await_args_list == [
        call("!STUDENT1", date(2024, 5, 13)),
        call("!STUDENT1", date(2024, 5, 20)),
    ]
    assert [event["id"] for event in events] == ["early", "middle", "late"]


async def test_coordinator_deduplicates_messages(hass, mock_wilma_client):
    """Test fetched messages are deduplicated by message id."""
    coordinator = WilmaCoordinator(
        hass, "https://test.inschool.fi", "testuser", "testpass", "test_entry_id"
    )

    first = await coordinator._async_update_data()
    second = await coordinator._async_update_data()

    assert len(first["students"]["!STUDENT1"]) == 2
    assert len(second["students"]["!STUDENT1"]) == 2
