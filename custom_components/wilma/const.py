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
SENSOR_NEXT_LESSON = "next_lesson"

BINARY_SENSOR_PROBLEM = "problem"
SENSOR_ATTENDANCE_COUNT = "attendance_count"
SENSOR_LATEST_ATTENDANCE = "latest_attendance"

STORAGE_KEY = f"{DOMAIN}_messages"
STORAGE_VERSION = 1

EVENT_NEW_MESSAGE = "wilma_new_message"
EVENT_NEW_ATTENDANCE = "wilma_new_attendance_mark"

SCHEDULE_WEEKS_AHEAD = 4  # number of weeks to fetch for the calendar
