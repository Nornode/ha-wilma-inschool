# Entities and Events

Entities are created per discovered student unless otherwise noted.

## Sensors

| Entity | Description |
| --- | --- |
| Latest Message | Subject of the latest message, with sender, timestamp, unread state, and optional content attributes. |
| Unread Messages | Number of unread messages. |
| Latest Bulletin | Latest bulletin/news item, with date, section, URL, and optional Markdown content attributes. |
| Unread Bulletins | Number of newly discovered bulletins in the latest refresh. |
| Next Lesson | Next upcoming timetable lesson, with date, start/end time, room, teachers, color, and long subject attributes. |
| Attendance Marks | Number of attendance marks in the current year, with unexplained count and mark-type breakdown. |
| Latest Attendance Mark | Most recent attendance mark and its parsed details. |
| Last Update | Timestamp of the last successful coordinator update. |

## Calendar

| Entity | Description |
| --- | --- |
| Schedule | Native Home Assistant calendar entity for the student's timetable. |

The calendar returns lessons with summary, start/end time, room, teacher description, and a stable Wilma-based UID when available.

## Binary Sensor

| Entity | Description |
| --- | --- |
| Problem | Diagnostic sensor that turns on when the latest update failed or when partial fetch errors were recorded. |

The `Problem` sensor has an `errors` attribute with recent fetch details.

## Events

| Event | When it fires | Useful payload fields |
| --- | --- | --- |
| `wilma_new_message` | A newly discovered message appears. | `student_id`, `student_name`, `subject`, `sender`, `timestamp`, `content` |
| `wilma_new_bulletin` | A newly discovered bulletin appears. | `student_id`, `student_name`, `news_id`, `title`, `date`, `section`, `url`, `content_markdown` |
| `wilma_new_attendance_mark` | A new attendance mark appears in the current-year attendance history. | `student_id`, `student_name`, `mark` |
