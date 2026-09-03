#!/usr/bin/env python3
"""Refresh live contribution totals and charts from GitHub GraphQL."""

from __future__ import annotations

import json
import html
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

LOGIN = os.environ.get("GITHUB_LOGIN", "serhii-kucherenko")
README = os.environ.get("README_PATH", "README.md")
CHART_PATH = os.environ.get(
    "CONTRIBUTION_CHART_PATH", "assets/contributions-by-year.svg"
)
START_YEAR = int(os.environ.get("START_YEAR", "2015"))
CHART_WIDTH = 760
CHART_HEIGHT = 260


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


def render_contribution_chart(year_counts: list[tuple[int, int]], updated: str) -> str:
    max_count = max((count for _, count in year_counts), default=0)
    scale_max = max(max_count, 1)
    chart_left = 58
    chart_top = 52
    chart_width = 650
    chart_height = 150
    bar_gap = 8
    bar_count = max(len(year_counts), 1)
    bar_width = (chart_width - bar_gap * (bar_count - 1)) / bar_count

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{CHART_WIDTH}" height="{CHART_HEIGHT}" viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" role="img" aria-labelledby="title desc">',
        "  <title id=\"title\">GitHub contributions by year</title>",
        f"  <desc id=\"desc\">Yearly contribution volume for {html.escape(LOGIN)}, refreshed {html.escape(updated)} UTC.</desc>",
        "  <rect width=\"100%\" height=\"100%\" rx=\"16\" fill=\"#0d1117\"/>",
        "  <text x=\"28\" y=\"32\" fill=\"#c9d1d9\" font-family=\"Inter,Segoe UI,Arial,sans-serif\" font-size=\"18\" font-weight=\"700\">GitHub contributions by year</text>",
        f"  <text x=\"28\" y=\"52\" fill=\"#8b949e\" font-family=\"Inter,Segoe UI,Arial,sans-serif\" font-size=\"12\">Live through {html.escape(updated)} UTC</text>",
    ]

    for step in range(5):
        value = round(scale_max * step / 4)
        y = chart_top + chart_height - (value / scale_max * chart_height)
        stroke = "#30363d" if step else "#8b949e"
        lines.extend(
            [
                f"  <line x1=\"{chart_left}\" y1=\"{y:.1f}\" x2=\"{chart_left + chart_width}\" y2=\"{y:.1f}\" stroke=\"{stroke}\" stroke-width=\"1\"/>",
                f"  <text x=\"{chart_left - 10}\" y=\"{y + 4:.1f}\" fill=\"#8b949e\" font-family=\"Inter,Segoe UI,Arial,sans-serif\" font-size=\"10\" text-anchor=\"end\">{format_int(value)}</text>",
            ]
        )

    for index, (year, count) in enumerate(year_counts):
        x = chart_left + index * (bar_width + bar_gap)
        height = count / scale_max * chart_height
        y = chart_top + chart_height - height
        center = x + bar_width / 2
        fill = "#58a6ff" if year != year_counts[-1][0] else "#f78166"
        lines.extend(
            [
                f"  <rect x=\"{x:.1f}\" y=\"{y:.1f}\" width=\"{bar_width:.1f}\" height=\"{height:.1f}\" rx=\"4\" fill=\"{fill}\">",
                f"    <title>{year}: {format_int(count)} contributions</title>",
                "  </rect>",
                f"  <text x=\"{center:.1f}\" y=\"{max(y - 6, 44):.1f}\" fill=\"#c9d1d9\" font-family=\"Inter,Segoe UI,Arial,sans-serif\" font-size=\"10\" text-anchor=\"middle\">{format_int(count)}</text>",
                f"  <text x=\"{center:.1f}\" y=\"{chart_top + chart_height + 20}\" fill=\"#8b949e\" font-family=\"Inter,Segoe UI,Arial,sans-serif\" font-size=\"10\" text-anchor=\"middle\">{year}</text>",
            ]
        )

    lines.extend(
        [
            "  <text x=\"58\" y=\"246\" fill=\"#8b949e\" font-family=\"Inter,Segoe UI,Arial,sans-serif\" font-size=\"11\">Orange marks the current year.</text>",
            "</svg>",
            "",
        ]
    )
    return "\n".join(lines)


def write_contribution_chart(year_counts: list[tuple[int, int]], updated: str) -> None:
    directory = os.path.dirname(CHART_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(CHART_PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_contribution_chart(year_counts, updated))


def main() -> None:
    auth = token()
    end_year = datetime.now(timezone.utc).year
    total = 0
    year_counts: list[tuple[int, int]] = []
    for year in range(START_YEAR, end_year + 1):
        count = year_total(auth, year)
        print(f"{year}: {count}")
        year_counts.append((year, count))
        total += count

    formatted = format_int(total)
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    stats_block = (
        "<!-- LIVE_STATS:START -->\n"
        f"**Live contribution total:** **{formatted}** (last refreshed {updated} UTC)\n"
        "<!-- LIVE_STATS:END -->"
    )
    chart_block = (
        "<!-- CONTRIBUTION_CHART:START -->\n"
        '<p align="center">\n'
        '  <img src="./assets/contributions-by-year.svg" alt="Yearly GitHub contribution volume chart" />\n'
        "</p>\n"
        "<!-- CONTRIBUTION_CHART:END -->"
    )

    path = README
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    stats_pattern = re.compile(r"<!-- LIVE_STATS:START -->.*?<!-- LIVE_STATS:END -->", re.S)
    chart_pattern = re.compile(
        r"<!-- CONTRIBUTION_CHART:START -->.*?<!-- CONTRIBUTION_CHART:END -->", re.S
    )
    if not stats_pattern.search(text):
        raise SystemExit("LIVE_STATS markers not found in README.md")
    if chart_pattern.search(text):
        text = chart_pattern.sub(chart_block, text)
    else:
        text = stats_pattern.sub(f"{stats_block}\n\n{chart_block}", text)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(stats_pattern.sub(stats_block, text))
    write_contribution_chart(year_counts, updated)
    print(f"Updated README live total to {formatted}")
    print(f"Updated contribution chart at {CHART_PATH}")


if __name__ == "__main__":
    main()
