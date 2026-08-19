# Wilma for Home Assistant

A Home Assistant integration for the [Wilma](https://www.vismasolutions.com/fi/produkter/wilma/) school platform. Monitor your children's school day directly from Home Assistant.

## Features

- **Multi-student support** — a separate HA device per child, named _Wilma {First name}_
- **Messages** — polls for new messages and fires a `wilma_new_message` event on each new one
- **Schedule & Calendar** — fetches the weekly timetable; provides a native HA calendar entity and a _Next Lesson_ sensor per student
- **Attendance** — full school-year attendance history with unexplained mark count and a `wilma_new_attendance_mark` event
- **Multilingual** — UI translated to English, Finnish and Swedish

## Quick Start

1. Add the integration via **Settings → Devices & Services → Add Integration → Wilma**.
2. Enter your Wilma server URL (e.g. `https://espoo.inschool.fi`), username and password.
3. Done — one device per student appears automatically.

## Example Automation

```yaml
automation:
  - alias: "Wilma — new message"
    trigger:
      platform: event
      event_type: wilma_new_message
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "{{ trigger.event.data.sender }}"
          message: "{{ trigger.event.data.subject }}"
```

See the [README](https://github.com/Nornode/ha-wilma-inschool#readme) for full documentation and more automation examples.
