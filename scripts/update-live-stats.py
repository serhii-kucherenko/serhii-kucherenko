#!/usr/bin/env python3
"""Refresh live contribution totals in README.md from GitHub GraphQL."""

from __future__ import annotations

import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

LOGIN = os.environ.get("GITHUB_LOGIN", "serhii-kucherenko")
README = os.environ.get("README_PATH", "README.md")
START_YEAR = int(os.environ.get("START_YEAR", "2015"))


def token() -> str:
    for key in ("PROFILE_STATS_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    raise SystemExit("Need PROFILE_STATS_TOKEN, GH_TOKEN, or GITHUB_TOKEN")


def graphql(query: str, auth: str, attempts: int = 5) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query}).encode("utf-8"),
        headers={
            "Authorization": f"bearer {auth}",
            "Content-Type": "application/json",
            "User-Agent": "serhii-kucherenko-live-stats",
        },
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(
                req, context=ssl.create_default_context(), timeout=60
            ) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in {502, 503, 504} or attempt == attempts:
                raise
            time.sleep(2 ** attempt)
        except TimeoutError as exc:
            last_error = exc
            if attempt == attempts:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GraphQL failed after retries: {last_error}")


def year_total(auth: str, year: int) -> int:
    from_ts = f"{year}-01-01T00:00:00Z"
    to_ts = f"{year}-12-31T23:59:59Z"
    query = (
        "query { user(login: \"%s\") { contributionsCollection(from: \"%s\", to: \"%s\") "
        "{ contributionCalendar { totalContributions } } } }"
        % (LOGIN, from_ts, to_ts)
    )
    payload = graphql(query, auth)
    try:
        return int(
            payload["data"]["user"]["contributionsCollection"]["contributionCalendar"][
                "totalContributions"
            ]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Failed for {year}: {json.dumps(payload)}") from exc


def format_int(n: int) -> str:
    return f"{n:,}"


def main() -> None:
    auth = token()
    end_year = datetime.now(timezone.utc).year
    total = 0
    for year in range(START_YEAR, end_year + 1):
        count = year_total(auth, year)
        print(f"{year}: {count}")
        total += count

    formatted = format_int(total)
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    block = (
        "<!-- LIVE_STATS:START -->\n"
        f"**Live contribution total:** **{formatted}** (last refreshed {updated} UTC)\n"
        "<!-- LIVE_STATS:END -->"
    )

    path = README
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    pattern = re.compile(r"<!-- LIVE_STATS:START -->.*?<!-- LIVE_STATS:END -->", re.S)
    if not pattern.search(text):
        raise SystemExit("LIVE_STATS markers not found in README.md")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(pattern.sub(block, text))
    print(f"Updated README live total to {formatted}")


if __name__ == "__main__":
    main()
