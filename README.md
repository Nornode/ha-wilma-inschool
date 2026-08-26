# Wilma for Home Assistant

> **Disclaimer:** This is an independent, community-developed project and is not affiliated with, endorsed by, or in any way connected to [Visma](https://www.visma.com/) or [Wilma](https://www.wilma.fi/). _Wilma_ and _Inschool_ are products of Visma Solutions Oy. Use of their service is subject to their own [accessibility statement](https://www.wilma.fi/sv/tillganglighetsutlatande/).

A Home Assistant integration for the [Wilma](https://www.wilma.fi/) school platform. Monitor your children's school day directly from Home Assistant — messages, timetables, lesson tracking and attendance history, all in one place.

[![Open your Home Assistant instance and add this repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Nornode&repository=ha-wilma-inschool&category=integration)
[![Open your Home Assistant instance and import the AI summary blueprint.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fraw.githubusercontent.com%2FNornode%2Fha-wilma-inschool%2Fmain%2Fblueprints%2Fautomation%2Fwilma%2Fai_entity_summary.yaml)

📖 **Full documentation lives in the [wiki](https://github.com/Nornode/ha-wilma-inschool/wiki)** — this README only covers what's needed to get started.

## Features

- **Multi-student support** — separate device per child, named _Wilma {First name}_
- **Messages & bulletins** — polls for new messages and school news, fires an event on each new one
- **Schedule & Calendar** — native HA calendar entity per student, plus a _Next Lesson_ sensor
- **Attendance** — full school-year history, tracks unexplained marks and fires an event on new ones
- **AI summaries** — a blueprint that turns long Wilma text into a real, dashboard-ready entity
- **Ready-made dashboards** — drop-in Lovelace YAML that discovers students automatically
- **Multilingual** — UI translated to English, Finnish and Swedish

See [wiki/Roadmap](https://github.com/Nornode/ha-wilma-inschool/wiki/Roadmap) for what's built and what's planned.

## Installation

**HACS (recommended):** click the _Add to HACS_ badge above, or add `https://github.com/Nornode/ha-wilma-inschool` as a custom repository (category **Integration**) and install _Wilma_ from HACS. Then restart Home Assistant.

**Manual:** copy `custom_components/wilma` into your Home Assistant `custom_components` directory and restart.

## Configuration

1. Go to **Settings → Devices & Services → Add Integration** and search for **Wilma**.
2. Enter your Wilma server URL (e.g. `https://espoo.inschool.fi`), username and password.

Options (scan interval, unread-only, content fetch limit, recent threshold, language) can be changed any time via **Configure** on the integration card.

## Entities

All entities live under the **Wilma {First name}** device (e.g. _Wilma StudentA_).

| Key                     | Type          | Description                                                                                                    |
| ----------------------- | ------------- | -------------------------------------------------------------------------------------------------------------- |
| `latest_message`        | Sensor        | Subject of the most recent message; full content in attributes                                                 |
| `unread_count`          | Sensor        | Count of unread messages                                                                                       |
| `latest_bulletin`       | Sensor        | Title of the most recent school bulletin; body in attributes                                                   |
| `unread_bulletin_count` | Sensor        | Count of bulletins not yet seen                                                                                |
| `next_lesson`           | Sensor        | Subject of the next upcoming lesson; start/end time, room and teacher in attributes                            |
| `attendance_count`      | Sensor        | Total attendance marks this school year; `unexplained_count` and `by_type` breakdown in attributes             |
| `latest_attendance`     | Sensor        | Most recent mark type; date, lesson hour, subject code and teacher in attributes                               |
| `summary_{key}`         | Sensor        | Stored AI summary; full text in the `summary` attribute. Created on demand — see [AI summaries](#ai-summaries) |
| `last_update`           | Sensor        | Timestamp of the last successful refresh (diagnostic)                                                          |
| `recent_message`        | Binary sensor | On when the latest message is within the recent threshold                                                      |
| `recent_bulletin`       | Binary sensor | On when the latest bulletin is within the recent threshold                                                     |
| `recent_attendance`     | Binary sensor | On when the latest attendance mark is within the recent threshold                                              |
| `schedule`              | Calendar      | Full timetable — shows in the HA Calendar UI and supports date-range queries                                   |

Two account-level entities live under a shared **Wilma** device:

| Entity                          | Type          | Description                                                  |
| ------------------------------- | ------------- | ------------------------------------------------------------ |
| `binary_sensor.wilma_problem`   | Binary sensor | On when the last refresh failed; error details in attributes |
| `sensor.wilma_last_http_status` | Sensor        | Last HTTP status seen while scraping (diagnostic)            |

## Events

All events include `entry_id`, `student_id` and `student_name`.

| Event                       | Additional payload                                                                                      | When fired                   |
| --------------------------- | ------------------------------------------------------------------------------------------------------- | ---------------------------- |
| `wilma_new_message`         | `message_id`, `subject`, `sender`, `timestamp`, `unread`, `content`, `content_html`, `content_markdown` | New message appears          |
| `wilma_new_bulletin`        | `news_id`, `title`, `date`, `section`, `url`, `content_html`, `content_markdown`                        | New school bulletin appears  |
| `wilma_new_attendance_mark` | `mark` (dict with `date`, `day`, `lesson_hour`, `subject_code`, `mark_type`, `teacher`)                 | New attendance mark detected |

## Services

| Service                     | Description                                                        |
| --------------------------- | ------------------------------------------------------------------ |
| `wilma.refresh`             | Force a data refresh                                               |
| `wilma.store_summary`       | Persist an AI summary and the prompt that produced it              |
| `wilma.summary_status`      | Ask whether a summary needs regenerating, without calling an agent |
| `wilma.store_summary_error` | Record a failed generation attempt, keeping the previous summary   |
| `wilma.clear_summary`       | Remove stored summaries                                            |

Full field reference: [wiki/Services](https://github.com/Nornode/ha-wilma-inschool/wiki/Services).

## Automation example

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

More triggers (`wilma_new_bulletin`, `wilma_new_attendance_mark`) work the same way — see the events table above for their payloads.

## AI summaries

Wilma messages are often long. Import the blueprint (button at the top, or
`blueprints/automation/wilma/ai_entity_summary.yaml`), point it at a source
entity such as `sensor.wilma_virppi_latest_message`, and it sends the text to
a conversation agent of your choice and stores the reply as
`sensor.wilma_{first_name}_summary_{key}` — no helper entities, no length
limit. The integration never calls an agent itself, so the prompt stays yours
to edit, and it skips regenerating a summary when the source text hasn't
changed, to save tokens.

Setup, prompt debugging and card examples: [wiki/AI-Summaries](https://github.com/Nornode/ha-wilma-inschool/wiki/AI-Summaries).

## Dashboards

Two ready-made Lovelace dashboards live under [`dashboards/`](dashboards/) and discover students automatically — no per-child editing required. See [wiki/Dashboards](https://github.com/Nornode/ha-wilma-inschool/wiki/Dashboards) for setup and screenshots.

## Development

```bash
git clone https://github.com/Nornode/ha-wilma-inschool
cd ha-wilma-inschool
./scripts/setup.sh
source .venv/bin/activate

pytest                                  # run tests
ruff check custom_components/wilma      # lint
mypy custom_components/wilma            # type check
```

Contributions are welcome — please feel free to submit a Pull Request.

## Credits

This integration is based on the original work by [Fredrik Wickström (@frwickst)](https://github.com/frwickst) — see [frwickst/wilma_ha](https://github.com/frwickst/wilma_ha). The upstream library powering the Wilma API client is [wilhelmina](https://github.com/frwickst/wilhelmina), also by Fredrik.

## License

MIT
