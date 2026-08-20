# Development

## Local Setup

```bash
git clone https://github.com/Nornode/ha-wilma-inschool
cd ha-wilma-inschool
./scripts/setup.sh
source .venv/bin/activate
```

## Tests

Run the full test suite:

```bash
pytest
```

Run with coverage:

```bash
pytest --cov=custom_components/wilma --cov-report=term-missing
```

## Quality Checks

```bash
ruff check custom_components/wilma tests
mypy custom_components/wilma
```

## Main Components

| File | Purpose |
| --- | --- |
| `custom_components/wilma/config_flow.py` | Home Assistant setup and options flow. |
| `custom_components/wilma/coordinator.py` | Login, polling, scraping, storage merge, and event firing. |
| `custom_components/wilma/sensor.py` | Message, bulletin, lesson, attendance, and update sensors. |
| `custom_components/wilma/calendar.py` | Per-student schedule calendar entity. |
| `custom_components/wilma/binary_sensor.py` | Diagnostic problem sensor. |

## Updating the Wiki

Edit the Markdown files in `wiki/` and commit them to the main repository. To update the live GitHub Wiki, sync the directory to a clone of `https://github.com/Nornode/ha-wilma-inschool.wiki.git` and push from that clone.
