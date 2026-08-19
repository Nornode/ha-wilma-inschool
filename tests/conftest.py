"""Fixtures for Wilma integration tests."""
import re
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


MOCK_NEWS_PAGES = {
        "!STUDENT1": """
        <html>
            <body>
                <h2>Tänään</h2>
                <ul>
                    <li><a href="/!STUDENT1/news/101">Kid One latest bulletin</a></li>
                </ul>
                <h2>Eilen</h2>
                <ul>
                    <li><a href="/!STUDENT1/news/100">Kid One older bulletin</a></li>
                </ul>
            </body>
        </html>
        """,
        "!STUDENT2": """
        <html>
            <body>
                <h2>Tänään</h2>
                <ul>
                    <li><a href="/!STUDENT2/news/201">Kid Two latest bulletin</a></li>
                </ul>
            </body>
        </html>
        """,
}

MOCK_NEWS_ARTICLES = {
        "!STUDENT1": {
                101: """
                <html>
                    <body>
                        <article>
                            <h1>Kid One latest bulletin</h1>
                            <p>Line one for kid one.</p>
                            <p><strong>Important</strong> update with a <a href="https://example.com">link</a>.</p>
                        </article>
                    </body>
                </html>
                """,
                100: """
                <html>
                    <body>
                        <article>
                            <h1>Kid One older bulletin</h1>
                            <p>Older content.</p>
                        </article>
                    </body>
                </html>
                """,
                102: """
                <html>
                    <body>
                        <article>
                            <h1>Kid One brand new bulletin</h1>
                            <p>Brand new bulletin body.</p>
                        </article>
                    </body>
                </html>
                """,
        },
        "!STUDENT2": {
                201: """
                <html>
                    <body>
                        <article>
                            <h1>Kid Two latest bulletin</h1>
                            <p>Line one for kid two.</p>
                        </article>
                    </body>
                </html>
                """,
        },
}


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
        def __init__(self) -> None:
            pass

        def get(self, *args, **kwargs):
            url = args[0] if args else ""
            url_path = url.split("?")[0]
            if url_path.endswith("/") or url_path.endswith("inschool.fi"):
                return _MockResponse(mock_wilma_client_discovery_html)
            if re.search(r"/news/\d+$", url_path):
                news_id = int(url_path.rsplit("/", 1)[-1])
                article = MOCK_NEWS_ARTICLES.get(client.user_id, {}).get(news_id, "<html><body></body></html>")
                return _MockResponse(article)
            if "/news" in url_path:
                return _MockResponse(MOCK_NEWS_PAGES.get(client.user_id, "<html><body></body></html>"))
            return _MockResponse(mock_wilma_client_discovery_html)

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
    client._ensure_session = AsyncMock(return_value=_MockSession())

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
