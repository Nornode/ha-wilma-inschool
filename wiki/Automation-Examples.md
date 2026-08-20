# Automation Examples

## Notify on New Message

```yaml
automation:
  - alias: "Wilma - new message notification"
    trigger:
      platform: event
      event_type: wilma_new_message
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "New message from {{ trigger.event.data.sender }}"
          message: "{{ trigger.event.data.subject }}"
```

## Notify on New Bulletin

```yaml
automation:
  - alias: "Wilma - new bulletin"
    trigger:
      platform: event
      event_type: wilma_new_bulletin
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "Wilma bulletin - {{ trigger.event.data.student_name }}"
          message: "{{ trigger.event.data.title }}"
```

## Notify on Unexplained Attendance Mark

```yaml
automation:
  - alias: "Wilma - attendance mark"
    trigger:
      platform: event
      event_type: wilma_new_attendance_mark
    action:
      - service: notify.mobile_app_your_phone
        data:
          title: "Attendance - {{ trigger.event.data.student_name }}"
          message: >
            {{ trigger.event.data.mark.mark_type }}
            {{ trigger.event.data.mark.date }}, hour {{ trigger.event.data.mark.lesson_hour }}
            {{ trigger.event.data.mark.subject_code }}
```

## Dashboard Snippet

```yaml
type: entities
title: Wilma today
entities:
  - entity: sensor.wilma_emma_next_lesson
  - entity: sensor.wilma_emma_unread_messages
  - entity: sensor.wilma_emma_unread_bulletins
  - entity: sensor.wilma_emma_attendance_marks
  - entity: calendar.wilma_emma_schedule
```
