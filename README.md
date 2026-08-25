# Wilma for Home Assistant

> **Disclaimer:** This is an independent, community-developed project and is not affiliated with, endorsed by, or in any way connected to [Visma](https://www.visma.com/) or [Wilma](https://www.wilma.fi/). _Wilma_ and _Inschool_ are products of Visma Solutions Oy. Use of their service is subject to their own [accessability](https://www.wilma.fi/sv/tillganglighetsutlatande/).

A Home Assistant integration for the [Wilma](https://www.wilma.fi/) school platform. Monitor your children's school day directly from Home Assistant — messages, timetables, lesson tracking and attendance history, all in one place.

## Features

- **Multi-student support** — separate device per child, named _Wilma {First name}_
- **Messages** — polls for new messages (every 30 minutes by default) and fires an event on each new one
- **Bulletins** — scrapes school news, tracks which items are new and fires an event for each
- **Schedule & Calendar** — fetches the timetable for the current and upcoming weeks; exposes a native HA calendar entity per student and a _Next Lesson_ sensor
- **Attendance** — fetches the full school-year attendance history; tracks unexplained marks and fires an event when new marks appear
- **AI summaries** — a blueprint plus services that store long AI summaries as real entities, with prompt history, staleness detection and token-saving skip rules
- **Ready-made dashboards** — drop-in Lovelace YAML that discovers students automatically
- **Multilingual UI** — config/options flow translated to English, Finnish and Swedish
- Configurable poll interval, unread-only mode, message-fetch limits and "recent" threshold

## Entities

Per-student entities live under the **Wilma {First name}** device (e.g. _Wilma Virppi_)
and are named `sensor.wilma_{first_name}_{key}`.

| Key | Type | Description |
| --- | --- | --- |
| `latest_message` | Sensor | Subject of the most recent message; full content in attributes |
| `unread_count` | Sensor | Count of unread messages |
| `latest_bulletin` | Sensor | Title of the most recent school bulletin; body in attributes |
| `unread_bulletin_count` | Sensor | Count of bulletins not yet seen |
| `next_lesson` | Sensor | Subject of the next upcoming lesson; start/end time, room and teacher in attributes |
| `attendance_count` | Sensor | Total attendance marks this school year; `unexplained_count` and `by_type` breakdown in attributes |
| `latest_attendance` | Sensor | Most recent mark type; date, lesson hour, subject code and teacher in attributes |
| `summary_{key}` | Sensor | Stored AI summary; full text in the `summary` attribute. Created on demand — see [AI summaries](wiki/AI-Summaries.md) |
| `last_update` | Sensor | Timestamp of the last successful refresh (diagnostic) |
| `recent_message` | Binary sensor | On when the latest message is within the recent threshold |
| `recent_bulletin` | Binary sensor | On when the latest bulletin is within the recent threshold |
| `recent_attendance` | Binary sensor | On when the latest attendance mark is within the recent threshold |
| `schedule` | Calendar | Full timetable — shows in the HA Calendar UI and supports date-range queries |

Two account-level entities live under a shared **Wilma** device:

| Entity | Type | Description |
| --- | --- | --- |
| `binary_sensor.wilma_problem` | Binary sensor | On when the last refresh failed; error details in attributes |
| `sensor.wilma_last_http_status` | Sensor | Last HTTP status seen while scraping (diagnostic) |

## Events

All events include `entry_id`, `student_id` and `student_name`.

| Event | Additional payload | When fired |
| --- | --- | --- |
| `wilma_new_message` | `message_id`, `subject`, `sender`, `timestamp`, `unread`, `content`, `content_html`, `content_markdown` | New message appears |
| `wilma_new_bulletin` | `news_id`, `title`, `date`, `section`, `url`, `content_html`, `content_markdown` | New school bulletin appears |
| `wilma_new_attendance_mark` | `mark` (dict with `date`, `day`, `lesson_hour`, `subject_code`, `mark_type`, `teacher`) | New attendance mark detected |

## Services

| Service | Description |
| --- | --- |
| `wilma.refresh` | Force a data refresh |
| `wilma.store_summary` | Persist an AI summary and the prompt that produced it |
| `wilma.summary_status` | Ask whether a summary needs regenerating, without calling an agent |
| `wilma.store_summary_error` | Record a failed generation attempt, keeping the previous summary |
| `wilma.clear_summary` | Remove stored summaries |

See [AI summaries](wiki/AI-Summaries.md) for the full field reference.

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

Options can be changed at any time via **Configure** on the integration card:

| Option | Default | Description |
| --- | --- | --- |
| Scan interval | 30 minutes | How often Wilma is polled |
| Only unread | off | Fetch only unread messages |
| No message content fetch limit | off | Fetch full content for every message, not just the newest few |
| Recent threshold | 24 hours | How long the `recent_*` binary sensors stay on |
| Language | Finnish | `langid` used for Wilma requests, which controls scraped label language |

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

For a one-off notification you can call an agent directly. For anything you want
to keep and display, use the blueprint described under [AI Summaries](#ai-summaries).

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
            {{ trigger.event.data.content_markdown or trigger.event.data.content }}
        response_variable: summary
      - service: notify.mobile_app_your_phone
        data:
          title: "Wilma — {{ trigger.event.data.sender }}"
          message: "{{ summary.response.speech.plain.speech }}"
```

## AI Summaries

Wilma messages are often long. This repository ships a blueprint that sends the
text to a Home Assistant conversation agent and stores the reply as a real
entity, so it can be rendered on a dashboard instead of only pushed to a phone.

- Blueprint: `blueprints/automation/wilma/ai_entity_summary.yaml`
- Storage: the `wilma.store_summary` service, persisted across restarts
- Result: `sensor.wilma_{first_name}_summary_{key}` with the full text in the
  `summary` attribute — no length limit and no helper entities to create

The integration never calls a conversation agent itself. The blueprint owns the
prompt, so the instructions stay yours to edit, and the exact prompt used is
stored alongside each summary for debugging.

To save tokens, the blueprint asks `wilma.summary_status` before each run and
skips the agent when the source text is unchanged, shorter than a configurable
minimum, or missing. Short messages are stored verbatim so the card is never
empty.

```yaml
alias: Wilma Virppi latest message AI summary
use_blueprint:
  path: wilma/ai_entity_summary.yaml
  input:
    source_entity: sensor.wilma_virppi_latest_message
    source_attribute: content_markdown
    summary_key: latest_message
    student: Virppi
    language: sv
    min_length: 500
    agent_id: conversation.google_ai_conversation
    instructions: >-
      Sammanfatta texten på lätt svenska i naturligt flytande språk, lätt
      uppställt för att läsa på en skärm. Lyft fram datum, tider och sådant
      som kräver en åtgärd av vårdnadshavaren.
```

Full setup, prompt debugging and card examples: [wiki/AI-Summaries.md](wiki/AI-Summaries.md).

## Dashboards

Two drop-in Lovelace configurations are included. Paste either into
**Settings → Dashboards → your dashboard → ⋮ → Raw configuration editor**.

| File | Needs HACS | Notes |
| --- | --- | --- |
| `dashboards/wilma_overview.yaml` | no | Zero configuration. Cards discover students via `integration_entities('wilma')`, so a new child appears automatically |
| `dashboards/wilma_overview_decluttering.yaml` | yes (`decluttering-card`) | Real tiles and tap actions; each student is one block with a single `student:` variable |

See [wiki/Dashboards.md](wiki/Dashboards.md).

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
title: Virppi — today
entities:
  - entity: sensor.wilma_virppi_next_lesson
    name: Next lesson
  - entity: sensor.wilma_virppi_attendance_count
    name: Attendance marks this year
  - entity: calendar.wilma_virppi_schedule
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

## Credits

This integration is based on the original work by [Fredrik Wickström (@frwickst)](https://github.com/frwickst) — see [frwickst/wilma_ha](https://github.com/frwickst/wilma_ha). The upstream library powering the Wilma API client is [wilhelmina](https://github.com/frwickst/wilhelmina), also by Fredrik.

## License

MIT
