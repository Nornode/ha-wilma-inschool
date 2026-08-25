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

ATTR_SUMMARY = "summary"
ATTR_SUMMARY_KEY = "key"
ATTR_TITLE = "title"
ATTR_PROMPT = "prompt"
ATTR_INSTRUCTIONS = "instructions"
ATTR_SOURCE_ENTITY = "source_entity"
ATTR_SOURCE_ATTRIBUTE = "source_attribute"
ATTR_SOURCE_ID = "source_id"
ATTR_SOURCE_HASH = "source_hash"
ATTR_SOURCE_LENGTH = "source_length"
ATTR_IS_STALE = "is_stale"
ATTR_GENERATED_BY = "generated_by"
ATTR_MIN_LENGTH = "min_length"
ATTR_ERROR = "error"
ATTR_LAST_ERROR = "last_error"
ATTR_LAST_ERROR_AT = "last_error_at"
ATTR_ERROR_COUNT = "error_count"
ATTR_AGENT_ID = "agent_id"
ATTR_GENERATED_AT = "generated_at"
ATTR_ENTRY_ID = "entry_id"
ATTR_STUDENT = "student"

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

SUMMARY_STORAGE_KEY = f"{DOMAIN}_summaries"
SUMMARY_HISTORY_LIMIT = 10
DEFAULT_SUMMARY_MIN_LENGTH = 500

GENERATED_BY_AGENT = "agent"
GENERATED_BY_PASSTHROUGH = "passthrough"

SERVICE_STORE_SUMMARY = "store_summary"
SERVICE_CLEAR_SUMMARY = "clear_summary"
SERVICE_SUMMARY_STATUS = "summary_status"
SERVICE_STORE_SUMMARY_ERROR = "store_summary_error"

SIGNAL_SUMMARY_ADDED = "wilma_summary_added_{}"
SIGNAL_SUMMARY_UPDATED = "wilma_summary_updated_{}"

EVENT_NEW_MESSAGE = "wilma_new_message"
EVENT_NEW_ATTENDANCE = "wilma_new_attendance_mark"
EVENT_NEW_BULLETIN = "wilma_new_bulletin"

SCHEDULE_WEEKS_AHEAD = 2  # current week plus next week
