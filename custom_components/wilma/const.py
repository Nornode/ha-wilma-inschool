"""Constants for the Wilma integration."""

from datetime import timedelta

DOMAIN = "wilma"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SERVER_URL = "server_url"
CONF_SCAN_INTERVAL_MINUTES = "scan_interval_minutes"
CONF_ONLY_UNREAD = "only_unread"
CONF_NO_MESSAGE_CONTENT_FETCH_LIMIT = "no_message_content_fetch_limit"

DEFAULT_SCAN_INTERVAL = timedelta(minutes=30)
DEFAULT_SCAN_INTERVAL_MINUTES = 30
DEFAULT_ONLY_UNREAD = False
DEFAULT_NO_MESSAGE_CONTENT_FETCH_LIMIT = False

ATTR_CONTENT = "content"
ATTR_CONTENT_MARKDOWN = "content_markdown"
ATTR_SENDER = "sender"
ATTR_SUBJECT = "subject"
ATTR_TIMESTAMP = "timestamp"
ATTR_ID = "id"
ATTR_STUDENT_ID = "student_id"
ATTR_STUDENT_NAME = "student_name"

SENSOR_LATEST_MESSAGE = "latest_message"
SENSOR_UNREAD_COUNT = "unread_count"

STORAGE_KEY = f"{DOMAIN}_messages"
STORAGE_VERSION = 1

EVENT_NEW_MESSAGE = "wilma_new_message"
