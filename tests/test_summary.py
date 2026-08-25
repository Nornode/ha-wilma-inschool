"""Tests for the Wilma summary service and summary sensors."""
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.wilma.const import (
    DOMAIN,
    SERVICE_CLEAR_SUMMARY,
    SERVICE_STORE_SUMMARY,
    SERVICE_STORE_SUMMARY_ERROR,
    SERVICE_SUMMARY_STATUS,
)

SOURCE_ENTITY = "sensor.fake_source"


def _set_source(hass: HomeAssistant, state: str, **attributes):
    hass.states.async_set(SOURCE_ENTITY, state, attributes)


async def _status(hass: HomeAssistant, **data):
    data.setdefault("key", "latest_message")
    data.setdefault("student", "Kid One")
    data.setdefault("source_entity", SOURCE_ENTITY)
    response = await hass.services.async_call(
        DOMAIN, SERVICE_SUMMARY_STATUS, data, blocking=True, return_response=True
    )
    await hass.async_block_till_done()
    return response


async def _store(hass: HomeAssistant, **data):
    await hass.services.async_call(DOMAIN, SERVICE_STORE_SUMMARY, data, blocking=True)
    await hass.async_block_till_done()


async def test_services_registered(hass: HomeAssistant, mock_setup_integration):
    """All summary services are registered on setup."""
    await mock_setup_integration()

    assert hass.services.has_service(DOMAIN, SERVICE_STORE_SUMMARY)
    assert hass.services.has_service(DOMAIN, SERVICE_CLEAR_SUMMARY)
    assert hass.services.has_service(DOMAIN, SERVICE_SUMMARY_STATUS)


async def test_status_reports_no_summary_for_long_text(
    hass: HomeAssistant, mock_setup_integration
):
    """A long source with no stored summary needs an agent call."""
    await mock_setup_integration()
    _set_source(hass, "Skolstart", content_markdown="C" * 800)

    status = await _status(hass, source_attribute="content_markdown", min_length=500)

    assert status["reason"] == "no_summary"
    assert status["needs_update"] is True
    assert status["call_agent"] is True
    assert status["source_text"].startswith("Skolstart\n\n")
    assert status["source_length"] == len("Skolstart\n\n") + 800


async def test_status_skips_agent_for_short_text(
    hass: HomeAssistant, mock_setup_integration
):
    """A short source is worth storing but not worth summarising."""
    await mock_setup_integration()
    _set_source(hass, "Kort", content_markdown="Skolan slutar 12.00.")

    status = await _status(hass, source_attribute="content_markdown", min_length=500)

    assert status["reason"] == "too_short"
    assert status["needs_update"] is True
    assert status["call_agent"] is False


async def test_status_reports_unchanged_source(
    hass: HomeAssistant, mock_setup_integration
):
    """An unchanged source needs no work at all."""
    await mock_setup_integration()
    _set_source(hass, "Skolstart", content_markdown="D" * 800)

    await _store(
        hass,
        key="latest_message",
        summary="stored summary",
        student="Kid One",
        source_entity=SOURCE_ENTITY,
        source_attribute="content_markdown",
    )

    status = await _status(hass, source_attribute="content_markdown", min_length=500)

    assert status["reason"] == "unchanged"
    assert status["needs_update"] is False
    assert status["call_agent"] is False
    assert status["stored_hash"] == status["source_hash"]


async def test_status_detects_changed_source(
    hass: HomeAssistant, mock_setup_integration
):
    """Editing the source marks the summary as needing a new agent call."""
    await mock_setup_integration()
    _set_source(hass, "Skolstart", content_markdown="E" * 800)

    await _store(
        hass,
        key="latest_message",
        summary="stored summary",
        student="Kid One",
        source_entity=SOURCE_ENTITY,
        source_attribute="content_markdown",
    )

    _set_source(hass, "Skolstart", content_markdown="F" * 800)
    status = await _status(hass, source_attribute="content_markdown", min_length=500)

    assert status["reason"] == "source_changed"
    assert status["call_agent"] is True


async def test_status_handles_missing_source(
    hass: HomeAssistant, mock_setup_integration
):
    """An unavailable source produces no work."""
    await mock_setup_integration()
    _set_source(hass, "unavailable")

    status = await _status(hass, min_length=500)

    assert status["reason"] == "no_source"
    assert status["needs_update"] is False


async def test_is_stale_tracks_source_changes(
    hass: HomeAssistant, mock_setup_integration
):
    """The sensor reports staleness live from the current source text."""
    await mock_setup_integration()
    _set_source(hass, "Skolstart", content_markdown="G" * 800)

    await _store(
        hass,
        key="latest_message",
        summary="stored summary",
        student="Kid One",
        source_entity=SOURCE_ENTITY,
        source_attribute="content_markdown",
    )

    state = hass.states.get("sensor.wilma_kid_summary_latest_message")
    assert state.attributes["is_stale"] is False
    assert state.attributes["generated_by"] == "agent"
    assert state.attributes["source_attribute"] == "content_markdown"

    _set_source(hass, "Skolstart", content_markdown="H" * 800)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.wilma_kid_summary_latest_message")
    assert state.attributes["is_stale"] is True


async def test_passthrough_summary_marked(hass: HomeAssistant, mock_setup_integration):
    """Short texts stored unchanged are labelled as passthrough."""
    await mock_setup_integration()
    _set_source(hass, "Kort", content_markdown="Skolan slutar 12.00.")

    await _store(
        hass,
        key="latest_message",
        summary="Skolan slutar 12.00.",
        student="Kid One",
        source_entity=SOURCE_ENTITY,
        source_attribute="content_markdown",
        generated_by="passthrough",
    )

    state = hass.states.get("sensor.wilma_kid_summary_latest_message")
    assert state.attributes["generated_by"] == "passthrough"
    assert state.attributes["is_stale"] is False


async def test_store_summary_creates_sensor_with_full_text(
    hass: HomeAssistant, mock_setup_integration
):
    """A stored summary creates a sensor exposing the full text and its prompt."""
    await mock_setup_integration()

    long_summary = "A" * 2000
    await _store(
        hass,
        key="latest_message",
        summary=long_summary,
        student="Kid One",
        title="Skolstart",
        prompt="Sammanfatta: rå text",
        instructions="Sammanfatta",
        source_entity="sensor.wilma_kid_latest_message",
        source_id="42",
        source_text="rå text",
        agent_id="conversation.test_agent",
    )

    state = hass.states.get("sensor.wilma_kid_summary_latest_message")
    assert state is not None
    assert state.state == "Skolstart"
    assert state.attributes["summary"] == long_summary
    assert state.attributes["prompt"] == "Sammanfatta: rå text"
    assert state.attributes["instructions"] == "Sammanfatta"
    assert state.attributes["source_entity"] == "sensor.wilma_kid_latest_message"
    assert state.attributes["source_id"] == "42"
    assert state.attributes["agent_id"] == "conversation.test_agent"
    assert state.attributes["source_hash"]
    assert state.attributes["generated_at"]
    assert state.attributes["student_id"] == "!STUDENT1"


async def test_state_falls_back_to_first_line_of_summary(
    hass: HomeAssistant, mock_setup_integration
):
    """Without a title the state is the first line, truncated to fit."""
    await mock_setup_integration()

    await _store(
        hass,
        key="digest",
        summary="First line\nSecond line",
        student="Kid One",
    )

    state = hass.states.get("sensor.wilma_kid_summary_digest")
    assert state.state == "First line"

    await _store(hass, key="long_title", summary="B" * 400, student="Kid One")
    state = hass.states.get("sensor.wilma_kid_summary_long_title")
    assert len(state.state) == 255
    assert state.state.endswith("...")


async def test_rewriting_summary_keeps_history(
    hass: HomeAssistant, mock_setup_integration
):
    """Storing the same key again moves the previous summary into history."""
    await mock_setup_integration()

    await _store(hass, key="latest_message", summary="first", student="Kid One", prompt="p1")
    await _store(hass, key="latest_message", summary="second", student="Kid One", prompt="p2")

    state = hass.states.get("sensor.wilma_kid_summary_latest_message")
    assert state.attributes["summary"] == "second"
    assert state.attributes["prompt"] == "p2"
    assert len(state.attributes["history"]) == 1
    assert state.attributes["history"][0]["summary"] == "first"
    assert state.attributes["history"][0]["prompt"] == "p1"


async def test_summary_survives_reload(hass: HomeAssistant, mock_setup_integration):
    """Stored summaries are restored from disk when the entry reloads."""
    entry = await mock_setup_integration()

    await _store(hass, key="latest_message", summary="persisted", student="Kid One")

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get("sensor.wilma_kid_summary_latest_message")
    assert state.attributes["summary"] == "persisted"


async def test_clear_summary_removes_stored_text(
    hass: HomeAssistant, mock_setup_integration
):
    """Clearing a key empties the summary attribute."""
    await mock_setup_integration()

    await _store(hass, key="latest_message", summary="gone soon", student="Kid One")

    await hass.services.async_call(
        DOMAIN,
        SERVICE_CLEAR_SUMMARY,
        {"key": "latest_message", "student": "Kid One"},
        blocking=True,
    )
    await hass.async_block_till_done()

    state = hass.states.get("sensor.wilma_kid_summary_latest_message")
    assert state.state in ("unknown", "")
    assert state.attributes.get("summary") is None


async def test_unknown_student_raises(hass: HomeAssistant, mock_setup_integration):
    """An unresolvable student is rejected."""
    await mock_setup_integration()

    with pytest.raises(ServiceValidationError):
        await _store(hass, key="latest_message", summary="text", student="Nobody")


async def test_missing_student_with_multiple_profiles_raises(
    hass: HomeAssistant, mock_setup_integration
):
    """Omitting the student is ambiguous when several students exist."""
    await mock_setup_integration()

    with pytest.raises(ServiceValidationError):
        await _store(hass, key="latest_message", summary="text")


async def test_empty_summary_rejected(hass: HomeAssistant, mock_setup_integration):
    """Whitespace-only summaries are not stored."""
    await mock_setup_integration()

    with pytest.raises(ServiceValidationError):
        await _store(hass, key="latest_message", summary="   ", student="Kid One")


async def _store_error(hass: HomeAssistant, **data):
    await hass.services.async_call(
        DOMAIN, SERVICE_STORE_SUMMARY_ERROR, data, blocking=True
    )
    await hass.async_block_till_done()


async def test_error_keeps_previous_summary(
    hass: HomeAssistant, mock_setup_integration
):
    """A failed attempt is recorded without discarding the last good summary."""
    await mock_setup_integration()

    await _store(hass, key="latest_message", summary="good summary", student="Kid One")
    await _store_error(
        hass, key="latest_message", student="Kid One", error="Agent timed out"
    )

    state = hass.states.get("sensor.wilma_kid_summary_latest_message")
    assert state.attributes["summary"] == "good summary"
    assert state.attributes["last_error"] == "Agent timed out"
    assert state.attributes["error_count"] == 1
    assert state.attributes["last_error_at"]


async def test_consecutive_errors_are_counted(
    hass: HomeAssistant, mock_setup_integration
):
    """Repeated failures increment the counter until a summary succeeds."""
    await mock_setup_integration()

    await _store_error(hass, key="latest_message", student="Kid One", error="one")
    await _store_error(hass, key="latest_message", student="Kid One", error="two")

    state = hass.states.get("sensor.wilma_kid_summary_latest_message")
    assert state.attributes["error_count"] == 2
    assert state.attributes["last_error"] == "two"
    assert state.attributes["summary"] is None

    await _store(hass, key="latest_message", summary="recovered", student="Kid One")

    state = hass.states.get("sensor.wilma_kid_summary_latest_message")
    assert state.attributes["error_count"] == 0
    assert state.attributes["last_error"] is None
    assert state.attributes["summary"] == "recovered"
