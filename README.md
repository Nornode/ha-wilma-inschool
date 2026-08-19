# Wilma for Home Assistant

> **Disclaimer:** This is an independent, community-developed project and is not affiliated with, endorsed by, or in any way connected to [Visma](https://www.visma.com/) or [Inschool](https://www.vismasolutions.com/fi/produkter/wilma/). _Wilma_ and _Inschool_ are products of Visma Solutions Oy. Use of their service is subject to their own [terms of use](https://help.wilma.fi/en/terms-of-use).

A Home Assistant integration for the [Wilma](https://www.vismasolutions.com/fi/produkter/wilma/) school platform. Monitor your children's school day directly from Home Assistant — messages, timetables, lesson tracking and attendance history, all in one place.

## Features

- **Multi-student support** — separate device per child, named _Wilma {First name}_
- **Messages** — polls for new messages every 15 minutes, fires an event on each new one
- **Schedule & Calendar** — fetches timetable for the current and upcoming weeks; exposes a native HA calendar entity per student and a _Next Lesson_ sensor
- **Attendance** — fetches the full school-year attendance history; tracks unexplained marks and fires an event when new marks appear
- **Multilingual UI** — config/options flow translated to English, Finnish and Swedish
- Configurable poll interval, unread-only mode and message-fetch limits

## Entities

All entities live under the **Wilma {First name}** device (e.g. _Wilma Emma_).

| Entity                   | Type     | Description                                                                                        |
| ------------------------ | -------- | -------------------------------------------------------------------------------------------------- |
| `latest_message`         | Sensor   | Subject of the most recent message; full content in attributes                                     |
| `unread_messages`        | Sensor   | Count of unread messages                                                                           |
| `next_lesson`            | Sensor   | Subject of the next upcoming lesson; start/end time, room and teacher in attributes                |
| `attendance_marks`       | Sensor   | Total attendance marks this school year; `unexplained_count` and `by_type` breakdown in attributes |
| `latest_attendance_mark` | Sensor   | Most recent mark type; date, lesson hour, subject code and teacher in attributes                   |
| `last_update`            | Sensor   | Timestamp of the last successful coordinator refresh                                               |
| `schedule`               | Calendar | Full timetable calendar — shows in the HA Calendar UI and supports date-range queries              |

## Events

| Event                       | Payload fields                                                            | When fired                                   |
| --------------------------- | ------------------------------------------------------------------------- | -------------------------------------------- |
| `wilma_new_message`         | `student_id`, `student_name`, `subject`, `sender`, `timestamp`, `content` | New message appears                          |
| `wilma_new_attendance_mark` | `student_id`, `student_name`, `mark` (dict)                               | New attendance mark detected in full history |

## Installation

### HACS (Recommended)

1. Make sure you have [HACS](https://hacs.xyz/) installed.
2. Add this repository as a custom repository in HACS:
   - Go to **HACS → Integrations → ⋮ → Custom repositories**
   - Add `https://github.com/Nornode/ha-wilma-inschool` with category **Integration**
3. Install _Wilma_ from HACS.
4. Restart Home Assistant.

### Manual Installation

1. Copy the `custom_components/wilma` folder to your Home Assistant `custom_components` directory.
2. Restart Home Assistant.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Wilma** and select it.
3. Enter your Wilma server URL (e.g. `https://espoo.inschool.fi`), username and password.
4. Click **Submit**.

Options (scan interval, unread-only, fetch limits) can be changed at any time via **Configure** on the integration card.

## Automation Examples

### Notify on new message

```yaml
automation:
  - alias: "Wilma — new message notification"
    trigger:
      platform: event
      event_type: wilma_new_message
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "New message from {{ trigger.event.data.sender }}"
          message: "{{ trigger.event.data.subject }}"
```

### AI-summarise a new message

```yaml
automation:
  - alias: "Wilma — AI message summary"
    trigger:
      platform: event
      event_type: wilma_new_message
    action:
      - service: conversation.process
        data:
          agent_id: homeassistant
          text: >
            Summarise this school message briefly:
            {{ trigger.event.data.content }}
        response_variable: summary
      - service: notify.mobile_app_your_phone
        data:
          title: "Wilma — {{ trigger.event.data.sender }}"
          message: "{{ summary.response.speech.plain.speech }}"
```

### Notify on unexplained attendance mark

```yaml
automation:
  - alias: "Wilma — unexplained attendance mark"
    trigger:
      platform: event
      event_type: wilma_new_attendance_mark
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "Attendance mark — {{ trigger.event.data.student_name }}"
          message: >
            {{ trigger.event.data.mark.mark_type }}
            {{ trigger.event.data.mark.date }}, hour {{ trigger.event.data.mark.lesson_hour }}
            ({{ trigger.event.data.mark.subject_code }})
```

### Dashboard — today's schedule card

```yaml
type: entities
title: Emma — today
entities:
  - entity: sensor.wilma_emma_next_lesson
    name: Next lesson
  - entity: sensor.wilma_emma_attendance_marks
    name: Attendance marks this year
  - entity: calendar.wilma_emma_schedule
```

## Development

### Setup

```bash
git clone https://github.com/Nornode/ha-wilma-inschool
cd ha-wilma-inschool
./scripts/setup.sh
source .venv/bin/activate
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=custom_components.wilma
```

### Quality Checks

```bash
# Run ruff for linting
ruff check custom_components/wilma

# Run mypy for type checking
mypy custom_components/wilma
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT
