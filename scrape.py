"""
Scrapes weekly lunch menus from two Linkosuo restaurants and generates index.html.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

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
]

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
    week: str = ""
    days: list[DayMenu] = field(default_factory=list)
    error: str = ""


def scrape_menu(restaurant: dict[str, str]) -> RestaurantMenu:
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


def today_weekday_fi() -> str:
    """Return today's Finnish weekday name prefix for highlighting."""
    names = ["Maanantai", "Tiistai", "Keskiviikko", "Torstai", "Perjantai", "Lauantai", "Sunnuntai"]
    return names[datetime.date.today().weekday()]


def render_day_card(day: DayMenu, today: str) -> str:
    is_today = day.day.startswith(today)
    highlight = ' day--today' if is_today else ''
    today_badge = '<span class="today-badge">Tänään</span>' if is_today else ''
    lines = [f"<p>{line}</p>" for line in day.items.splitlines() if line.strip()]
    items_html = "\n".join(lines)
    return f"""
        <div class="day{highlight}">
            <h3 class="day__name">{day.day} {today_badge}</h3>
            <div class="day__items">{items_html}</div>
        </div>"""


def render_restaurant(menu: RestaurantMenu, today: str) -> str:
    if menu.error:
        body = f'<p class="error">Virhe haettaessa ruokalistaa: {menu.error}</p>'
    elif not menu.days:
        body = '<p class="error">Ruokalistaa ei löydy tälle viikolle.</p>'
    else:
        body = "\n".join(render_day_card(d, today) for d in menu.days)

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
            Avaa Linkosuo.fi ↗
        </a>
        <div class="days">
            {body}
        </div>
    </section>"""


def render_html(menus: list[RestaurantMenu]) -> str:
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=2)))
    updated = now.strftime("%-d.%-m.%Y klo %H:%M")
    today = today_weekday_fi()
    restaurants_html = "\n".join(render_restaurant(m, today) for m in menus)

    return f"""<!DOCTYPE html>
<html lang="fi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lounaslista – Hertta & Orvokki</title>
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
        <span>Hertta &amp; Orvokki – Hervanta</span>
        <span class="updated">Päivitetty {updated}</span>
    </header>
    <main>
        {restaurants_html}
    </main>
    <footer>
        Tiedot haettu automaattisesti sivuilta
        <a href="https://linkosuo.fi" target="_blank" rel="noopener">linkosuo.fi</a>.
        Lähdekoodi:
        <a href="https://github.com/agent-tk/lounaslista" target="_blank" rel="noopener">
            github.com/agent-tk/lounaslista
        </a>
    </footer>
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
