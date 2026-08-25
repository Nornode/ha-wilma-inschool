# TODO: AI summaries and dashboards

Canonical checklist. Mirrored for readers in `wiki/Roadmap.md`.
Broader integration backlog lives in `TODO-data-points.md`.

## Done

### Phase 1 — Integration-owned summary storage

- [x] **1.1 `wilma.store_summary` service.** Fields: `key`, `summary`, `student`,
      `title`, `prompt`, `instructions`, `source_entity`, `source_attribute`,
      `source_id`, `source_text`, `agent_id`, `generated_by`, `entry_id`.
- [x] **1.2 Persistence** in `wilma_summaries_<entry_id>`, last 10 versions per
      key kept as `history`.
- [x] **1.3 `WilmaSummarySensor`** per student per key, created dynamically via
      dispatcher when a key is first stored.
- [x] **1.4 `wilma.clear_summary`** (per key / per student / all).
- [x] **1.5 Blueprint rewritten** to call `wilma.store_summary`; the three
      `input_text` helpers and the 765-character ceiling are gone.
- [x] **1.6 Tests** — service registration, round-trip, restore-after-reload,
      long text, history, validation errors.

### Phase 2 — Token saving and reliability

- [x] **2.1 Staleness and skip rules.** `wilma.summary_status` returns
      `needs_update` / `call_agent` / `reason`; the agent is skipped when the
      source is unchanged, below `min_length` (default 500), or missing. Short
      texts are stored verbatim as `generated_by: passthrough`. `is_stale` is
      recomputed live from the current source text.
- [x] **2.5 Error surface.** `wilma.store_summary_error` records `last_error`,
      `last_error_at` and `error_count` without discarding the previous summary.
      `error_count` resets on the next success.

### Phase 3 — Dashboards

- [x] **3.1 `dashboards/wilma_overview.yaml`** — zero-config; discovers students
      via `integration_entities('wilma')`.
- [x] **3.2 Card snippets** documented in `wiki/Dashboards.md`.
- [x] **3.3 `dashboards/wilma_overview_decluttering.yaml`** — one `[[student]]`
      variable per student.
- [x] **3.4 Multi-student** — both dashboards handle any number of students
      without editing entity ids.
- [x] **3.5 History card** — recent errors plus the last three summaries per key.
- [x] **3.6 Dashboard tests** — `tests/test_dashboards.py` parses both files and
      compiles every Markdown template.

### Phase 4 — Documentation

- [x] **4.2 Wiki rewritten** for the service-based flow, with a migration
      section for the old helper setup, plus new Dashboards, Services, Roadmap
      and Home pages.
- [x] **4.4 README and `info.md`** updated; stale helper-based instructions,
      wrong poll interval and the missing bulletin/service reference removed.

## Planned

Ordered by expected value.

- [ ] **2.2 Structured output.** Ask the agent for JSON and parse into
      `title`, `summary`, `action_required`, `due_date`,
      `category` (info / event / permission-slip / absence / other) and
      `urgency`. Fall back to plain text when parsing fails.
- [ ] **2.3 Derived entities.** Binary sensor "action required", next-deadline
      sensor, calendar entries for extracted dates.
- [ ] **3.7 Urgency-coloured cards** driven by `2.2`.
- [ ] **2.4 Daily digest.** One summary per student across all unread messages,
      bulletins and attendance. New blueprint `ai_daily_digest.yaml` on a
      scheduled trigger.
- [ ] **2.6 Cost guard.** Minimum interval per key plus an optional daily call
      budget in the options flow.
- [ ] **4.1 Options toggle.** "Enable AI summaries" with agent and language
      picked once, so blueprints can default to them.
- [ ] **4.3 Prompt library.** Tested instruction blocks per source type
      (message, bulletin, attendance, weekly schedule) in Swedish, Finnish and
      English.
- [ ] **4.5 Repair issue** after N consecutive generation failures.
- [ ] **4.6 Dashboard screenshot** in the README.
