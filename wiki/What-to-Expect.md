# What to Expect

This integration polls Wilma and exposes the data Home Assistant can use reliably for dashboards, notifications, and automations. It does not replace Wilma, and it does not try to provide every Wilma feature.

## Expected Behavior

- After setup, each discovered student appears as a separate Home Assistant device named `Wilma {First name}`.
- Data refreshes on a configurable interval. The default is 30 minutes.
- New messages, bulletins, and attendance marks can trigger Home Assistant events.
- Message and bulletin content may be available as Markdown attributes when the integration can fetch the full item body.
- The schedule calendar can return events for requested date ranges, while the next lesson sensor focuses on the next upcoming timetable entry.

## Current Scope

Supported today:

- Messages and unread message count.
- Bulletins/news and newly discovered bulletin count.
- Timetable calendar and next lesson sensor.
- Current-year attendance history and unexplained attendance count.
- Basic diagnostics through the `Problem` binary sensor.

Not currently in scope:

- Sending messages or replies through Wilma.
- Editing attendance explanations.
- Managing courses, grades, exams, homework, or forms unless they are later added explicitly.
- Guaranteed behavior across every Wilma municipality or school environment. Wilma HTML and endpoints can vary.

## Reliability Notes

Wilma is a cloud service and this integration depends on Wilma login, session cookies, HTML structure, and upstream API behavior. Temporary Wilma outages, changed page layouts, rejected login token requests, or school-specific settings can affect the integration.

This integration has been tested with the Espoo Wilma instance at `https://espoo.inschool.fi`.

When something fails, check the `Problem` binary sensor attributes first. It reports recent fetch errors such as unexpected HTTP statuses or partial scrape failures.
