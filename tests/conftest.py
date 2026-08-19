"""Fixtures for Wilma integration tests."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for every test in this package."""
    yield

from custom_components.wilma.const import (
    CONF_PASSWORD,
    CONF_SERVER_URL,
    CONF_USERNAME,
    DOMAIN,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integration loading in all tests."""
    yield


@pytest.fixture
def mock_config_entry():
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SERVER_URL: "https://test.inschool.fi",
            CONF_USERNAME: "testuser",
            CONF_PASSWORD: "testpass",
        },
        entry_id="test",
    )


class MockWilmaMessage:
    """Mock Wilma message."""

    def __init__(
        self,
        msg_id,
        subject,
        sender,
        timestamp,
        unread=False,
        content_html=None,
        folder="Inbox",
    ):
        """Initialize mock message."""
        self.id = msg_id
        self.subject = subject
        self.sender = sender
        self.timestamp = timestamp
        self.unread = unread
        self.content_html = content_html
        self.folder = folder
        self.sender_id = msg_id
        self.sender_type = 1
        self.allow_forward = True
        self.allow_reply = True
        self.reply_list = []
        self.senders = []

    def format_timestamp(self):
        """Return timestamp."""
        # Mock implementation
        return self.timestamp

    @property
    def content_markdown(self):
        """Return content as markdown."""
        if not self.content_html:
            raise ValueError("Message content is not available")
        return f"Markdown version of: {self.content_html}"


@pytest.fixture
def mock_wilma_client(mock_wilma_client_discovery_html):
    """Return a mock Wilma client."""
    student_messages = {
        "!STUDENT1": [
            MockWilmaMessage(
                1,
                "Test Message 1",
                "Sender 1",
                "2023-01-02 12:00",
                True,
                "<p>Test content 1</p>",
            ),
            MockWilmaMessage(
                2,
                "Test Message 2",
                "Sender 2",
                "2023-01-01 12:00",
                False,
                "<p>Test content 2</p>",
            ),
        ],
        "!STUDENT2": [
            MockWilmaMessage(
                11,
                "Test Message 11",
                "Sender 11",
                "2023-01-03 12:00",
                True,
                "<p>Test content 11</p>",
            )
        ],
    }

    class _MockResponse:
        def __init__(self, html: str) -> None:
            self.status = 200
            self._html = html

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self):
            return self._html

    class _MockSession:
        def __init__(self, html: str) -> None:
            self._html = html

        def get(self, *args, **kwargs):
            return _MockResponse(self._html)

    client = MagicMock()
    client.user_id = None
    client._sid = None
    client.base_url = "https://test.inschool.fi"

    async def login(username, password):
        client.user_id = "!STUDENT1"
        client._sid = "sid"

    async def get_messages(**kwargs):
        return student_messages.get(client.user_id, student_messages["!STUDENT1"])

    client.login = AsyncMock(side_effect=login)
    client.get_messages = AsyncMock(side_effect=get_messages)
    client.get_message_content = AsyncMock(return_value=student_messages["!STUDENT1"][0])
    client.close = AsyncMock()
    client._ensure_session = AsyncMock(
        return_value=_MockSession(mock_wilma_client_discovery_html)
    )

    with patch("custom_components.wilma.coordinator.WilmaClient", return_value=client):
        yield client


@pytest.fixture
def mock_wilma_client_discovery_html():
    """Return mock HTML payload with two discoverable student IDs."""
    return """
    <html>
      <body>
                <a href="/!STUDENT1/messages">Kid One</a>
                <a href="/!STUDENT2/messages">Kid Two</a>
      </body>
    </html>
    """


@pytest.fixture
def mock_wilma_flow_client(mock_wilma_client_discovery_html):
    """Return a mock Wilma client for config flow validation."""
    messages = [
        MockWilmaMessage(
            1,
            "Test Message 1",
            "Sender 1",
            "2023-01-02 12:00",
            True,
            "<p>Test content 1</p>"
        ),
    ]

    client = MagicMock()
    client.user_id = "!STUDENT1"
    client._sid = "sid"
    client.base_url = "https://test.inschool.fi"
    client.login = AsyncMock()
    client.get_messages = AsyncMock(return_value=messages)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("custom_components.wilma.config_flow.WilmaClient", return_value=client):
        yield client


@pytest.fixture
def mock_wilma_exception_client():
    """Return a mock Wilma client that raises exceptions."""
    from wilhelmina import AuthenticationError
    
    client = MagicMock()
    client.login = AsyncMock(side_effect=AuthenticationError("Auth failed"))
    client.get_messages = AsyncMock(return_value=[])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with patch("custom_components.wilma.config_flow.WilmaClient", return_value=client):
        yield client


@pytest.fixture
def mock_setup_integration(hass, mock_config_entry, mock_wilma_client):
    """Set up the Wilma integration in Home Assistant."""

    async def _setup_integration():
        mock_config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        return mock_config_entry

    return _setup_integration