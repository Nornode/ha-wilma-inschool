#!/usr/bin/env python3
"""Probe Wilma client calls and dump raw responses.

Usage:
    export WILMA_SERVER_URL="https://example.inschool.fi"
    export WILMA_USERNAME="your-username"
    export WILMA_PASSWORD="your-password"
    python3 scripts/probe_endpoints.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import aiohttp  # noqa: E402
from wilhelmina import AuthenticationError, WilmaClient, WilmaError  # noqa: E402

DUMP_DIR = Path("/tmp")

# Candidate endpoints to probe beyond messages — common Wilma sections
_CANDIDATE_ENDPOINTS: list[tuple[str, str]] = [
    ("news", "{user_id}/news"),
    ("news_list", "{user_id}/news/list"),
    ("schedule", "{user_id}/schedule"),
    ("timetable", "{user_id}/timetable"),
    ("absences", "{user_id}/absences"),
    ("absences_list", "{user_id}/absences/list"),
    ("excuses", "{user_id}/excuses"),
    ("grades", "{user_id}/grades"),
    ("assessments", "{user_id}/assessments"),
    ("assessment_list", "{user_id}/assessments/list"),
    ("notes", "{user_id}/notes"),
    ("notes_list", "{user_id}/notes/list"),
    ("homework", "{user_id}/homework"),
    ("portfolio", "{user_id}/portfolio"),
    ("profile", "{user_id}/profile"),
    ("contacts", "{user_id}/contacts"),
    ("guardians", "{user_id}/guardians"),
    ("index", "{user_id}/index"),
    ("primus", "{user_id}/primus"),
]


def _serialize(value: Any) -> Any:
    """Convert unknown objects to JSON-safe values for diagnostics."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize(v) for v in value]
    if hasattr(value, "__dict__"):
        return _serialize(vars(value))
    return value


def _dump(name: str, payload: Any) -> Path:
    path = DUMP_DIR / f"wilma_probe_{name}.json"
    path.write_text(json.dumps(_serialize(payload), indent=2, ensure_ascii=False))
    return path


def _show_message_keys(messages: list[Any], label: str) -> None:
    if not messages:
        return
    first = _serialize(messages[0])
    if isinstance(first, dict):
        print(f"  Keys in {label}: {list(first.keys())}")


def _show_full_message_fields(message: Any) -> None:
    """Print every field of a Message object to surface unused data."""
    serialized = _serialize(message)
    if not isinstance(serialized, dict):
        return
    print("  All fields on first message:")
    for key, value in serialized.items():
        preview = json.dumps(value, ensure_ascii=False)
        if len(preview) > 120:
            preview = preview[:117] + "..."
        print(f"    {key}: {preview}")


async def _probe_home_page(client: WilmaClient, session: aiohttp.ClientSession) -> dict[str, Any]:
    """Fetch the home page and extract navigation links / available sections."""
    print("\n[home_page] Fetching authenticated home page...")
    headers = {"Wilma2SID": client._sid or ""}
    try:
        async with session.get(client.base_url, headers=headers) as resp:
            if resp.status != 200:
                print(f"  SKIP: status {resp.status}")
                return {}
            html = await resp.text()
            # Extract all hrefs containing the user_id prefix — real nav links
            pattern = re.compile(r'href=["\']([^"\'>]*' + re.escape(client.user_id or "!") + r'[^"\'>]*)["\']')
            links = sorted(set(pattern.findall(html)))
            # Also grab any /api/ or /json/ paths
            api_links = sorted(set(re.findall(r'href=["\']([^"\'>]*/(?:api|json|list)[^"\'>]*)["\']', html)))
            result = {"user_links": links, "api_links": api_links, "page_size_bytes": len(html.encode())}
            dump_path = _dump("home_page", result)
            print(f"  OK: {len(links)} user-scoped links, {len(api_links)} api/list links -> {dump_path}")
            if links:
                print("  Sample links:")
                for link in links[:15]:
                    print(f"    {link}")
            return result
    except Exception as err:
        print(f"  ERROR: {type(err).__name__}: {err}")
        return {}


async def _probe_candidate_endpoints(
    client: WilmaClient, session: aiohttp.ClientSession
) -> dict[str, int]:
    """Try each candidate endpoint and report HTTP status codes."""
    print("\n[candidate_endpoints] Probing Wilma section endpoints...")
    results: dict[str, int] = {}
    headers = {"Wilma2SID": client._sid or ""}

    for name, template in _CANDIDATE_ENDPOINTS:
        path = template
        if "{user_id}" in template and client.user_id:
            path = template.format(user_id=client.user_id)
        url = f"{client.base_url}/{path.lstrip('/')}"
        try:
            # Try JSON first
            async with session.get(url, headers={**headers, "Accept": "application/json"}, allow_redirects=False) as resp:
                results[name] = resp.status
                content_type = resp.headers.get("Content-Type", "")
                print(f"  {resp.status}  {name:30s}  {url}  ({content_type.split(';')[0].strip()})")
                if resp.status == 200 and "json" in content_type:
                    try:
                        data = await resp.json()
                        dump_path = _dump(f"endpoint_{name}", data)
                        top_keys = list(data.keys()) if isinstance(data, dict) else f"list[{len(data)}]"
                        print(f"         -> JSON keys: {top_keys}  dumped to {dump_path}")
                    except Exception:
                        pass
                elif resp.status == 200:
                    text = await resp.text()
                    dump_path = _dump(f"endpoint_{name}_html", {"html_size": len(text), "snippet": text[:500]})
                    print(f"         -> HTML ({len(text)} bytes) dumped to {dump_path}")
        except Exception as err:
            results[name] = -1
            print(f"  ERR  {name:30s}  {type(err).__name__}: {err}")

    _dump("candidate_endpoints_status", results)
    return results


async def _run_probe(server_url: str, username: str, password: str) -> int:
    has_playwright = importlib.util.find_spec("playwright") is not None
    print(f"Playwright available: {has_playwright}")
    print("Logging in...")

    try:
        async with WilmaClient(server_url) as client:
            await client.login(username, password)
            print(f"  Login OK  (user_id={client.user_id})")

            # Obtain the raw aiohttp session for direct endpoint probing
            raw_session: aiohttp.ClientSession = await client._ensure_session()

            # ── 1. Home page navigation discovery ────────────────────────────
            await _probe_home_page(client, raw_session)

            # ── 2. Candidate section endpoints ───────────────────────────────
            await _probe_candidate_endpoints(client, raw_session)

            # ── 3. get_messages() variants ───────────────────────────────────
            after_week = datetime.now(timezone.utc) - timedelta(days=7)
            message_calls: list[tuple[str, dict[str, Any]]] = [
                ("messages_default", {}),
                ("messages_only_unread", {"only_unread": True}),
                ("messages_with_content", {"with_content": True}),
                ("messages_after_week", {"after": after_week}),
                (
                    "messages_with_content_after_week",
                    {"with_content": True, "after": after_week},
                ),
                (
                    "messages_no_limit",
                    {"with_content": True, "after": after_week, "no_message_content_fetch_limit": True},
                ),
            ]

            successful = 0
            first_message_id: int | None = None

            for name, kwargs in message_calls:
                print(f"\n[{name}] get_messages({kwargs})")
                try:
                    messages = await client.get_messages(**kwargs)
                except TypeError as err:
                    print(f"  SKIP: method signature mismatch: {err}")
                    _dump(f"{name}_error", {"error": str(err), "kwargs": kwargs})
                    continue
                except Exception as err:
                    print(f"  ERROR: {type(err).__name__}: {err}")
                    _dump(f"{name}_error", {"error": str(err), "kwargs": kwargs})
                    continue

                count = len(messages) if hasattr(messages, "__len__") else -1
                dump_path = _dump(name, messages)
                print(f"  OK: {count} message(s) -> {dump_path}")
                _show_message_keys(messages, "first message")

                if count and count > 0:
                    msg = messages[0]
                    if first_message_id is None:
                        first_message_id = getattr(msg, "id", None)
                    _show_full_message_fields(msg)

                successful += 1

            # ── 4. get_message_content() for first available message ──────────
            if first_message_id is not None:
                print(f"\n[get_message_content] id={first_message_id}")
                try:
                    full = await client.get_message_content(first_message_id)
                    dump_path = _dump("message_content_full", full)
                    print(f"  OK -> {dump_path}")
                    _show_full_message_fields(full)
                except Exception as err:
                    print(f"  ERROR: {type(err).__name__}: {err}")

            print("\nDone.")
            print("  Dumps: /tmp/wilma_probe_*.json")
            if successful == 0:
                print("  No successful probe calls.")
                return 1
            return 0

    except AuthenticationError as err:
        print(f"ERROR: authentication failed: {err}")
        return 2
    except WilmaError as err:
        print(f"ERROR: Wilma API error: {err}")
        return 3


async def main() -> int:
    server_url = os.environ.get("WILMA_SERVER_URL")
    username = os.environ.get("WILMA_USERNAME")
    password = os.environ.get("WILMA_PASSWORD")

    missing = [
        name
        for name, value in (
            ("WILMA_SERVER_URL", server_url),
            ("WILMA_USERNAME", username),
            ("WILMA_PASSWORD", password),
        )
        if not value
    ]
    if missing:
        print(f"ERROR: missing environment variable(s): {', '.join(missing)}")
        return 4

    return await _run_probe(server_url, username, password)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
