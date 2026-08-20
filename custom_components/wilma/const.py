"""Constants for the Wilma integration."""

import json
from datetime import timedelta
from pathlib import Path

DOMAIN = "wilma"
INTEGRATION_VERSION = json.loads(
    Path(__file__).with_name("manifest.json").read_text(encoding="utf-8")
)["version"]
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SERVER_URL = "server_url"
CONF_SCAN_INTERVAL_MINUTES = "scan_interval_minutes"
CONF_ONLY_UNREAD = "only_unread"
CONF_NO_MESSAGE_CONTENT_FETCH_LIMIT = "no_message_content_fetch_limit"
CONF_LANGUAGE = "language"
CONF_RECENT_THRESHOLD_HOURS = "recent_threshold_hours"

DEFAULT_SCAN_INTERVAL = timedelta(minutes=30)
DEFAULT_SCAN_INTERVAL_MINUTES = 30
DEFAULT_ONLY_UNREAD = False
DEFAULT_NO_MESSAGE_CONTENT_FETCH_LIMIT = False
DEFAULT_LANGUAGE = "1"  # Finnish
DEFAULT_RECENT_THRESHOLD_HOURS = 24

ATTR_CONTENT = "content"
ATTR_CONTENT_MARKDOWN = "content_markdown"
ATTR_SENDER = "sender"
ATTR_SUBJECT = "subject"
ATTR_TIMESTAMP = "timestamp"
ATTR_ID = "id"
ATTR_STUDENT_ID = "student_id"
ATTR_STUDENT_NAME = "student_name"
ATTR_NEWS_ID = "news_id"
ATTR_NEWS_DATE = "date"
ATTR_NEWS_SECTION = "section"
ATTR_NEWS_URL = "url"

SENSOR_LATEST_MESSAGE = "latest_message"
SENSOR_UNREAD_COUNT = "unread_count"
SENSOR_NEXT_LESSON = "next_lesson"
SENSOR_LATEST_BULLETIN = "latest_bulletin"
SENSOR_UNREAD_BULLETIN_COUNT = "unread_bulletin_count"

BINARY_SENSOR_PROBLEM = "problem"
BINARY_SENSOR_RECENT_MESSAGE = "recent_message"
BINARY_SENSOR_RECENT_BULLETIN = "recent_bulletin"
BINARY_SENSOR_RECENT_ATTENDANCE = "recent_attendance"
SENSOR_ATTENDANCE_COUNT = "attendance_count"
SENSOR_LATEST_ATTENDANCE = "latest_attendance"
SENSOR_LAST_HTTP_STATUS = "last_http_status"

STORAGE_KEY = f"{DOMAIN}_messages"
STORAGE_VERSION = 1

EVENT_NEW_MESSAGE = "wilma_new_message"
EVENT_NEW_ATTENDANCE = "wilma_new_attendance_mark"
EVENT_NEW_BULLETIN = "wilma_new_bulletin"

SCHEDULE_WEEKS_AHEAD = 2  # current week plus next week
