import asyncio
import time
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import callogic as cl
from valo_sdk import Extension

ext = Extension()
TICK = 30
ICS_EVERY = 900
NAME = {
    "uk": "Календар",
    "ru": "Календарь",
    "en": "Calendar",
    "de": "Kalender",
    "es": "Calendario",
    "fr": "Calendrier",
    "ja": "カレンダー",
}
ext.device(
    "calendar",
    NAME,
    [
        {"id": "workday", "type": "bool", "access": "r"},
        {"id": "tomorrow_workday", "type": "bool", "access": "r"},
        {"id": "holiday", "type": "text", "access": "r"},
        {"id": "event", "type": "text", "access": "r"},
        {"id": "next_event", "type": "text", "access": "r"},
        {"id": "next_holiday", "type": "text", "access": "r"},
    ],
    kind="calendar",
    model="Calendar",
)
wd = cl.Workdays(
    str(ext.settings.get("country") or "FI"),
    str(ext.settings.get("holidays_off") or "auto"),
    str(ext.settings.get("extra_off") or ""),
    str(ext.settings.get("extra_work") or ""),
)
st: dict[str, Any] = {
    "tz": ZoneInfo("Europe/Helsinki"),
    "lang": "uk",
    "events": [],
    "ics_at": 0.0,
    "ics_error": "",
    "ics_stats": {},
    "last": None,
}


def now() -> datetime:
    return datetime.now(st["tz"])


def name(n: cl.Names | None, lang: str | None = None) -> str:
    return (n.get(lang or st["lang"]) or n.get("en") or "") if n else ""


def ics_url() -> str:
    url = str(ext.settings.get("ics_url") or "").strip()
    return "https://" + url[len("webcal://") :] if url.lower().startswith("webcal://") else url


def fetch_ics(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Valo smart home"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read(5_000_000).decode("utf-8", "replace")


def occurrences(t: datetime, back: int = 1, ahead: int = 8) -> list[dict[str, Any]]:
    return cl.expand(st["events"], t - timedelta(days=back), t + timedelta(days=ahead), st["tz"])


@ext.on_start
async def start() -> None:
    try:
        home = await ext.call("home")
        st["tz"] = ZoneInfo(home.get("timezone") or "Europe/Helsinki")
        st["lang"] = home.get("lang") or "uk"
    except Exception as e:
        ext.log.warning("home info unavailable: %s", e)


async def refresh_ics() -> None:
    url = ics_url()
    if not url or time.time() - st["ics_at"] < ICS_EVERY:
        return
    st["ics_at"] = time.time()
    if not url.lower().startswith(("https://", "http://")):
        st["ics_error"] = "ics_url must start with https://"
        ext.log.error("calendar url rejected: unsupported scheme")
        return
    try:
        text = await asyncio.to_thread(fetch_ics, url)
        stats: dict[str, int] = {}
        st["events"] = cl.parse_ics(text, st["tz"], stats)
        st["ics_error"] = ""
        st["ics_stats"] = stats
        ext.log.info(
            "calendar loaded, events %s, skipped %s, unsupported repeat rules %s",
            len(st["events"]),
            stats["skipped"],
            stats["unsupported"],
        )
        if stats["skipped"] or stats["unsupported"]:
            ext.log.warning(
                "calendar: %s events skipped as invalid, %s repeat rules shown as single events",
                stats["skipped"],
                stats["unsupported"],
            )
    except Exception as e:
        st["ics_error"] = type(e).__name__
        ext.log.error("calendar download failed: %s", type(e).__name__)


def when(o: dict[str, Any]) -> str:
    s = o["start"].astimezone(st["tz"])
    return f"{s:%d.%m}" if o["all_day"] else f"{s:%d.%m %H:%M}"


def fmt_occ(o: dict[str, Any]) -> str:
    return f"{when(o)} {o['title']}"


async def tick() -> None:
    await refresh_ics()
    t = now()
    today = t.date()
    occ = occurrences(t)
    cur = cl.active(occ, t)
    nxt = next((o for o in occ if o["start"] > t), None)
    nh = wd.next_holiday(today + timedelta(days=1))
    values = {
        "workday": wd.is_workday(today),
        "tomorrow_workday": wd.is_workday(today + timedelta(days=1)),
        "holiday": name(wd.holiday(today)),
        "event": ", ".join(o["title"] for o in cur),
        "next_event": fmt_occ(nxt) if nxt else "",
        "next_holiday": f"{nh[0]:%d.%m} {name(nh[1])}" if nh else "",
    }
    await ext.state("calendar", values)
    if values != st.get("pub"):
        st["pub"] = values
        await ext.changed("calendar", "today")
    last = st["last"]
    if last is not None:
        for o in occ:
            info = {"title": o["title"], "start": fmt_occ(o), "all_day": o["all_day"]}
            if last < o["start"] <= t:
                await ext.trigger("event_start", info)
                ext.log.info("event start %s", o["title"])
            if last < o["end"] <= t:
                await ext.trigger("event_end", info)
    st["last"] = t


@ext.loop
async def loop() -> None:
    while True:
        try:
            await tick()
        except Exception as e:
            ext.log.error("calendar tick failed: %s", e)
        await asyncio.sleep(TICK)


def day_of(params: dict) -> date:
    return now().date() + timedelta(days=1 if params.get("day") == "tomorrow" else 0)


def answer(ok: bool, value: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "outs": [[0, payload] if ok else [1]],
        "trace": {"s": "ok" if ok else "no", "m": "ext_value", "p": {"value": value, "target": "-"}},
    }


@ext.block("workday")
async def b_workday(params: dict, token: dict, dry: bool) -> dict:
    d = day_of(params)
    ok = wd.is_workday(d)
    return answer(ok, d.isoformat(), {"day": d.strftime("%d.%m.%Y")})


@ext.block("holiday")
async def b_holiday(params: dict, token: dict, dry: bool) -> dict:
    d = day_of(params)
    h = name(wd.holiday(d))
    return answer(bool(h), h or d.isoformat(), {"holiday": h, "day": d.strftime("%d.%m.%Y")})


@ext.block("in_event")
async def b_in_event(params: dict, token: dict, dry: bool) -> dict:
    contains = str(params.get("contains") or "")
    hit = [o for o in cl.active(occurrences(now()), now()) if cl.matches(o["title"], contains)]
    return answer(bool(hit), hit[0]["title"] if hit else contains, {"title": hit[0]["title"] if hit else ""})


@ext.block("event_on")
async def b_event_on(params: dict, token: dict, dry: bool) -> dict:
    contains = str(params.get("contains") or "")
    d = day_of(params)
    hit = [o for o in cl.on_day(occurrences(now(), 1, 3), d, st["tz"]) if cl.matches(o["title"], contains)]
    return answer(bool(hit), hit[0]["title"] if hit else contains, {"title": hit[0]["title"] if hit else ""})


def L(uk: str, ru: str, en: str) -> dict[str, str]:
    return {"uk": uk, "ru": ru, "en": en}


def yes(v: bool) -> dict[str, str]:
    return L("робочий", "рабочий", "workday") if v else L("вихідний", "выходной", "day off")


def summary(lang: str) -> dict[str, Any]:
    today = now().date()
    h = wd.holiday(today)
    nh = wd.next_holiday(today + timedelta(days=1))
    items: list[dict[str, Any]] = [
        {"label": L("Сьогодні", "Сегодня", "Today"), "value": yes(wd.is_workday(today))},
        {"label": L("Завтра", "Завтра", "Tomorrow"), "value": yes(wd.is_workday(today + timedelta(days=1)))},
    ]
    if h:
        items.append({"label": L("Свято", "Праздник", "Holiday"), "value": name(h, lang)})
    if nh:
        items.append(
            {
                "label": L("Наступне свято", "Следующий праздник", "Next holiday"),
                "value": f"{nh[0]:%d.%m} {name(nh[1], lang)}",
            }
        )
    return {"type": "stats", "items": items}


@ext.page("calendar")
async def page_calendar(params: dict) -> dict:
    lang = str(params.get("lang") or st["lang"])
    blocks: list[dict[str, Any]] = [{"type": "clock"}, summary(lang)]
    if ics_url():
        occ = [o for o in occurrences(now(), 0, 7) if o["end"] > now()]
        blocks.append(
            {
                "type": "list",
                "label": L("Події на 7 днів", "События на 7 дней", "Events for 7 days"),
                "items": [{"text": o["title"], "value": when(o)} for o in occ[:30]],
            }
        )
        skipped, unsupported = st["ics_stats"].get("skipped", 0), st["ics_stats"].get("unsupported", 0)
        if skipped or unsupported:
            blocks.append(
                {
                    "type": "text",
                    "text": L(
                        f"Пропущено подій з помилками: {skipped}, повторів, показаних одним разом: {unsupported}",
                        f"Пропущено событий с ошибками: {skipped}, повторов, показанных одним разом: {unsupported}",
                        f"Invalid events skipped: {skipped}, repeat rules shown once: {unsupported}",
                    ),
                }
            )
        if st["ics_error"]:
            blocks.append(
                {
                    "type": "text",
                    "text": L(
                        f"Помилка календаря: {st['ics_error']}",
                        f"Ошибка календаря: {st['ics_error']}",
                        f"Calendar error: {st['ics_error']}",
                    ),
                }
            )
    if wd.country:
        blocks.append(
            {
                "type": "list",
                "label": L("Найближчі свята", "Ближайшие праздники", "Upcoming holidays"),
                "items": [{"text": name(n, lang), "value": f"{d:%d.%m.%Y}"} for d, n in wd.upcoming(now().date(), 8)],
            }
        )
    note = L(
        "Свята враховуються як вихідні" if wd.off else "Свята не є вихідними (воєнний стан або налаштування)",
        "Праздники считаются выходными" if wd.off else "Праздники не выходные (военное положение или настройка)",
        "Holidays are days off" if wd.off else "Holidays are working days (martial law or setting)",
    )
    blocks.append({"type": "text", "text": note})
    return {"blocks": blocks, "updated": now().isoformat()}


@ext.page("today")
async def page_today(params: dict) -> dict:
    blocks: list[dict[str, Any]] = [{"type": "clock"}, summary(str(params.get("lang") or st["lang"]))]
    cur = cl.active(occurrences(now()), now())
    if cur:
        blocks.append(
            {
                "type": "list",
                "label": L("Зараз", "Сейчас", "Now"),
                "items": [{"text": o["title"], "value": ""} for o in cur],
            }
        )
    return {"blocks": blocks}


if __name__ == "__main__":
    ext.run()
