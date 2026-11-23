"""
Decide whether a scheduled run should scrape again (standard library only).

GitHub delays scheduled workflows by hours, so the workflow runs often and
this script skips the scrape when index.html is already fresh: generated
today (Helsinki time) and every restaurant shows the target week's list.
The target week is the current ISO week, or next week on Sat/Sun so that a
list published over the weekend is picked up before Monday.

Prints "refresh=true" or "refresh=false" (append to $GITHUB_OUTPUT).
"""

from __future__ import annotations

import datetime
import re
import sys
from zoneinfo import ZoneInfo


def needs_refresh(html: str, now: datetime.datetime) -> tuple[bool, str]:
    m = re.search(r'<body data-generated="([^"]+)"', html)
    if not m:
        return True, "no generation time in index.html"
    generated = datetime.datetime.fromisoformat(m.group(1))
    if generated.astimezone(now.tzinfo).date() != now.date():
        return True, f"generated {generated:%Y-%m-%d}, not today"

    target = now.date()
    if target.weekday() >= 5:
        target += datetime.timedelta(days=7 - target.weekday())
    target_week = target.isocalendar().week

    sections = re.findall(r'<section class="restaurant"([^>]*)>', html)
    if not sections:
        return True, "no restaurants in index.html"
    for attrs in sections:
        name = re.search(r'data-name="([^"]*)"', attrs)
        week = re.search(r'data-week="(\d+)"', attrs)
        label = name.group(1) if name else "?"
        if not week:
            return True, f"{label}: no week (error or missing list)"
        if int(week.group(1)) != target_week:
            return True, f"{label}: week {week.group(1)}, want {target_week}"
    return False, f"all lists are for week {target_week} and generated today"


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "index.html"
    try:
        with open(path, encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        html = ""
    refresh, reason = needs_refresh(html, datetime.datetime.now(ZoneInfo("Europe/Helsinki")))
    print(reason, file=sys.stderr)
    print(f"refresh={'true' if refresh else 'false'}")


if __name__ == "__main__":
    main()
