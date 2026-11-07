"""
Scrapes weekly lunch menus (Linkosuo Hertta & Orvokki, Caffitella Duo Tampere)
and generates index.html.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

RESTAURANTS = [
    {
        "name": "Hertta",
        "subtitle": "Hermiankatu 1, Hervanta",
        "url": "https://linkosuo.fi/toimipaikka/hertta/",
    },
    {
        "name": "Orvokki",
        "subtitle": "Hermiankatu 6–8, Hervanta",
        "url": "https://linkosuo.fi/toimipaikka/lounasravintola-orvokki/",
    },
    {
        "name": "Caffitella Duo",
        "subtitle": "Kauppakeskus Duo, Hervanta",
        "url": "https://www.caffitella.fi/lounaslista/",
        "source": "caffitella",
        "match": "Duo",
        "link_label": "Avaa Caffitella.fi ↗",
    },
]

WEEKDAYS = [
    "maanantai", "tiistai", "keskiviikko", "torstai",
    "perjantai", "lauantai", "sunnuntai",
]
DAY_RE = re.compile(r"^(" + "|".join(WEEKDAYS) + r")\b\W*(.*)$", re.I)
BLOCK_TAGS = {
    "p", "div", "li", "ul", "ol", "br", "tr", "td", "table", "section",
    "h1", "h2", "h3", "h4", "h5", "h6", "figure", "blockquote",
}
HEADING_TAGS = ["h1", "h2", "h3", "h4"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; lounaslista-bot/1.0; "
        "+https://github.com/agent-tk/lounaslista)"
    )
}


@dataclass
class DayMenu:
    day: str
    items: str


@dataclass
class RestaurantMenu:
    name: str
    subtitle: str
    url: str
    link_label: str = "Avaa Linkosuo.fi ↗"
    week: str = ""
    days: list[DayMenu] = field(default_factory=list)
    error: str = ""


def scrape_menu(restaurant: dict[str, str]) -> RestaurantMenu:
    if restaurant.get("source") == "caffitella":
        return scrape_caffitella(restaurant)
    return scrape_linkosuo(restaurant)


def _section_lines(heading) -> list[str]:
    """Text lines from everything after `heading` up to the next heading of the
    same or higher level (works regardless of how the content is nested)."""
    level = int(heading.name[1])
    stop = {f"h{i}" for i in range(1, level + 1)}
    parts: list[str] = []
    for el in heading.next_elements:
        name = getattr(el, "name", None)
        if name:
            if name in stop or name == "footer":
                break
            if name in BLOCK_TAGS:
                parts.append("\n")
        elif el.parent is not None and el.parent.name not in ("script", "style"):
            if type(el).__name__ == "NavigableString":
                parts.append(str(el))
    lines = []
    for line in "".join(parts).split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
    return lines


def parse_caffitella(html: str, match: str) -> tuple[str, list[DayMenu], str]:
    """Return (week label, days, error) for the Caffitella list whose heading
    contains `match` (e.g. "Duo")."""
    soup = BeautifulSoup(html, "html.parser")
    heading = None
    for h in soup.find_all(HEADING_TAGS):
        if match.lower() in h.get_text(" ", strip=True).lower():
            heading = h
            break
    if heading is None:
        return "", [], f"Listaa, jossa mainitaan {match}, ei löydy"

    lines = _section_lines(heading)
    preamble: list[str] = []
    days: list[DayMenu] = []
    day_name, items = "", []

    def flush() -> None:
        if day_name:
            days.append(DayMenu(day=day_name, items="\n".join(items)))

    for line in lines:
        # The allergen legend ("G = gluteeniton | ...") marks the end of the list
        if day_name and re.search(r"\b[GLM]\s*=\s*\w", line):
            break
        m = DAY_RE.match(line)
        if m:
            flush()
            rest = m.group(2).strip()
            day_name = m.group(1).capitalize()
            items = []
            # "MAANANTAI 3.11." -> date belongs to the label; anything longer is a dish
            if rest and re.fullmatch(r"[\d.\s–-]+", rest):
                day_name = f"{day_name} {rest}"
            elif rest:
                items.append(rest)
        elif day_name:
            items.append(line)
        else:
            preamble.append(line)
    flush()

    intro = " ".join(preamble)
    week = ""
    wm = re.search(r"(?:vko|viikko)\.?\s*(\d{1,2})", intro, re.I)
    if wm:
        week = f"Viikko {wm.group(1)}"
    else:
        dm = re.search(r"\d{1,2}\.?\s*[–-]\s*\d{1,2}\.\d{1,2}\.?", intro)
        if dm:
            week = dm.group(0)
    return week, days, ""


def scrape_caffitella(restaurant: dict[str, str]) -> RestaurantMenu:
    result = RestaurantMenu(
        name=restaurant["name"],
        subtitle=restaurant["subtitle"],
        url=restaurant["url"],
        link_label=restaurant.get("link_label", "Avaa sivusto ↗"),
    )
    try:
        resp = requests.get(restaurant["url"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        result.week, result.days, result.error = parse_caffitella(
            resp.text, restaurant.get("match", "Duo")
        )
    except Exception as exc:
        result.error = str(exc)
    return result


def scrape_linkosuo(restaurant: dict[str, str]) -> RestaurantMenu:
    result = RestaurantMenu(
        name=restaurant["name"],
        subtitle=restaurant["subtitle"],
        url=restaurant["url"],
    )
    try:
        resp = requests.get(restaurant["url"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Find the "Lounaslista" heading, then the <dl> that follows it.
        # Structure: h3 > button > div > dl > div#current-week > h4, dt, dd, ...
        lounaslista = soup.find("h3", string=re.compile("Lounaslista", re.I))
        if not lounaslista:
            result.error = "Lounaslista-osiota ei löydy"
            return result

        dl = lounaslista.find_next("dl")
        if not dl:
            result.error = "Ruokalista-elementtiä ei löydy"
            return result

        # The first <div> inside <dl> contains the current week
        week_div = dl.find("div")
        if not week_div:
            result.error = "Viikko-elementtiä ei löydy"
            return result

        week = ""
        days: list[DayMenu] = []
        current_day = ""

        for child in week_div.children:
            if not hasattr(child, "name") or not child.name:
                continue
            tag = child.name

            if tag == "h4":
                week = child.get_text(strip=True)
            elif tag == "dt":
                current_day = child.get_text(strip=True)
            elif tag == "dd" and current_day:
                # Items are separated by <br> tags
                items = child.get_text(separator="\n", strip=True)
                days.append(DayMenu(day=current_day, items=items))
                current_day = ""

        result.week = week
        result.days = days

    except Exception as exc:
        result.error = str(exc)

    return result


def render_day_card(day: DayMenu) -> str:
    lines = [f"<p>{line}</p>" for line in day.items.splitlines() if line.strip()]
    items_html = "\n".join(lines)
    return f"""
        <div class="day" data-day="{day.day}">
            <h3 class="day__name">{day.day}</h3>
            <div class="day__items">{items_html}</div>
        </div>"""


def render_restaurant(menu: RestaurantMenu) -> str:
    if menu.error:
        body = f'<p class="error">Virhe haettaessa ruokalistaa: {menu.error}</p>'
    elif not menu.days:
        body = '<p class="error">Ruokalistaa ei löydy tälle viikolle.</p>'
    else:
        body = "\n".join(render_day_card(d) for d in menu.days)

    week_label = f'<span class="week-label">{menu.week}</span>' if menu.week else ""
    return f"""
    <section class="restaurant">
        <div class="restaurant__header">
            <div>
                <h2 class="restaurant__name">{menu.name}</h2>
                <p class="restaurant__subtitle">{menu.subtitle}</p>
            </div>
            {week_label}
        </div>
        <a class="restaurant__link" href="{menu.url}" target="_blank" rel="noopener">
            {menu.link_label}
        </a>
        <div class="days">
            {body}
        </div>
    </section>"""


def render_html(menus: list[RestaurantMenu]) -> str:
    now = datetime.datetime.now(ZoneInfo("Europe/Helsinki"))
    updated = now.strftime("%-d.%-m.%Y klo %H:%M")
    restaurants_html = "\n".join(render_restaurant(m) for m in menus)

    return f"""<!DOCTYPE html>
<html lang="fi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lounaslista – Hertta, Orvokki & Duo</title>
    <style>
        *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

        body {{
            font-family: system-ui, -apple-system, sans-serif;
            background: #f5f5f0;
            color: #222;
            min-height: 100vh;
        }}

        header {{
            background: #2e7d32;
            color: #fff;
            padding: 1.25rem 1.5rem;
            display: flex;
            align-items: baseline;
            gap: 1rem;
            flex-wrap: wrap;
        }}
        header h1 {{ font-size: 1.5rem; font-weight: 700; }}
        header .updated {{
            font-size: 0.8rem;
            opacity: 0.75;
            margin-left: auto;
        }}

        main {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 1.5rem 1rem;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 1.5rem;
        }}

        .restaurant {{
            background: #fff;
            border-radius: 10px;
            box-shadow: 0 2px 8px rgba(0,0,0,.08);
            overflow: hidden;
        }}
        .restaurant__header {{
            background: #388e3c;
            color: #fff;
            padding: 1rem 1.25rem;
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
        }}
        .restaurant__name {{ font-size: 1.3rem; font-weight: 700; }}
        .restaurant__subtitle {{ font-size: 0.8rem; opacity: 0.85; margin-top: 0.2rem; }}
        .week-label {{
            background: rgba(255,255,255,.2);
            padding: .2rem .6rem;
            border-radius: 20px;
            font-size: 0.8rem;
            white-space: nowrap;
        }}
        .restaurant__link {{
            display: block;
            text-align: right;
            padding: .35rem 1.25rem;
            font-size: 0.75rem;
            color: #388e3c;
            text-decoration: none;
            background: #f1f8f1;
            border-bottom: 1px solid #e0ede0;
        }}
        .restaurant__link:hover {{ text-decoration: underline; }}

        .days {{ padding: .75rem 1.25rem 1.25rem; display: flex; flex-direction: column; gap: .75rem; }}

        .day {{
            border: 1px solid #e8e8e8;
            border-radius: 8px;
            padding: .75rem 1rem;
            transition: border-color .15s;
        }}
        .day--today {{
            border-color: #2e7d32;
            background: #f1f8f1;
        }}

        .day__name {{
            font-size: 0.9rem;
            font-weight: 600;
            color: #444;
            margin-bottom: .4rem;
            display: flex;
            align-items: center;
            gap: .5rem;
        }}
        .day--today .day__name {{ color: #2e7d32; }}

        .today-badge {{
            background: #2e7d32;
            color: #fff;
            font-size: 0.65rem;
            font-weight: 700;
            padding: .1rem .45rem;
            border-radius: 20px;
            letter-spacing: .03em;
        }}

        .day__items p {{
            font-size: 0.82rem;
            line-height: 1.5;
            color: #333;
            padding: .15rem 0;
        }}
        .day__items p + p {{
            border-top: 1px dashed #eee;
        }}

        .error {{ color: #c62828; font-size: 0.85rem; padding: 1rem 1.25rem; }}

        footer {{
            text-align: center;
            padding: 1.5rem;
            font-size: 0.75rem;
            color: #888;
        }}
        footer a {{ color: #888; }}
    </style>
</head>
<body>
    <header>
        <h1>🍽️ Lounaslista</h1>
        <span>Hertta, Orvokki &amp; Caffitella Duo – Hervanta</span>
        <span class="updated">Päivitetty {updated}</span>
    </header>
    <main>
        {restaurants_html}
    </main>
    <footer>
        Tiedot haettu automaattisesti sivuilta
        <a href="https://linkosuo.fi" target="_blank" rel="noopener">linkosuo.fi</a> ja
        <a href="https://www.caffitella.fi/lounaslista/" target="_blank" rel="noopener">caffitella.fi</a>.
        Lähdekoodi:
        <a href="https://github.com/agent-tk/lounaslista" target="_blank" rel="noopener">
            github.com/agent-tk/lounaslista
        </a>
    </footer>
    <script>
        // Highlight today's menu card in the browser so it's always correct
        // regardless of when the page was last generated.
        (function () {{
            var DAYS = ["Sunnuntai","Maanantai","Tiistai","Keskiviikko","Torstai","Perjantai","Lauantai"];
            var todayPrefix = DAYS[new Date().getDay()];
            document.querySelectorAll(".day").forEach(function (el) {{
                if ((el.dataset.day || "").startsWith(todayPrefix)) {{
                    el.classList.add("day--today");
                    var h3 = el.querySelector(".day__name");
                    if (h3) {{
                        var badge = document.createElement("span");
                        badge.className = "today-badge";
                        badge.textContent = "Tänään";
                        h3.appendChild(badge);
                    }}
                }}
            }});
        }})();
    </script>
</body>
</html>"""


def main() -> None:
    menus = [scrape_menu(r) for r in RESTAURANTS]
    html = render_html(menus)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    for m in menus:
        if m.error:
            print(f"  ERROR {m.name}: {m.error}")
        else:
            print(f"  OK    {m.name}: {m.week}, {len(m.days)} days")
    print("Wrote index.html")


if __name__ == "__main__":
    main()
