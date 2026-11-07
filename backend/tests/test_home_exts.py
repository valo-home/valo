import asyncio
import importlib
import json
import pathlib
import sys
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "extensions" / "packages" / "fi.valo.energy"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "extensions" / "packages" / "fi.valo.openmeteo"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "extensions" / "packages" / "fi.valo.calendar"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "extensions" / "packages" / "fi.valo.timers"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "extensions" / "packages" / "fi.valo.safety"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "extensions" / "packages" / "fi.valo.plugguard"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "extensions" / "sdk"))
import callogic as cl
import energylogic as el
import omlogic as om
import plugguardlogic as pl
import safetylogic as sl
import timerlogic as tl

ROOT = pathlib.Path(__file__).resolve().parents[2] / "extensions"
PKGS = ROOT / "packages"
HEL = ZoneInfo("Europe/Helsinki")


def test_energy_counter_and_power() -> None:
    st: dict = {}
    plug = {"id": "p", "state": {"kwh": 10.0, "w": 100}, "available": True}
    assert el.delta(st, plug, 0) == 0
    plug["state"]["kwh"] = 10.5
    assert el.delta(st, plug, 60) == 0.5
    plug["state"]["kwh"] = 0.2
    assert el.delta(st, plug, 120) == 0.2
    plug["state"]["kwh"] = 500
    assert el.delta(st, plug, 180) == 0
    st2: dict = {}
    only_w = {"id": "w", "state": {"w": 1000}, "available": True}
    el.delta(st2, only_w, 0)
    assert el.delta(st2, only_w, 3600) == 0
    assert el.delta(st2, only_w, 3660) == pytest.approx(1000 * 60 / 3600 / 1000, abs=1e-6)
    only_w["available"] = False
    assert el.delta(st2, only_w, 3720) == 0


def test_energy_price_and_totals() -> None:
    assert el.unit_price({"fixed_price": 0.1, "transfer": 0.05}) == pytest.approx(0.15)
    assert el.unit_price({}) == 0
    devs = [
        {"id": "a", "source": "zigbee", "caps": [{"id": "kwh"}]},
        {"id": "b", "source": "zigbee", "caps": [{"id": "t"}]},
        {"id": "c", "source": "ext", "caps": [{"id": "w"}]},
        {"id": "d", "source": "zigbee", "caps": [{"id": "w"}]},
        {"id": "x", "kind": "price", "state": {"p": 42.0}, "caps": [{"id": "p"}]},
    ]
    assert [d["id"] for d in el.meters(devs, {"d"})] == ["a"]
    assert el.auto_main([{"id": "m", "kind": "meter"}, {"id": "p", "kind": "plug"}]) == "m"
    assert el.auto_main([{"id": "m", "kind": "meter"}, {"id": "n", "kind": "meter"}]) is None
    ledger: dict = {}
    today = date(2026, 11, 5)
    el.record(ledger, today, "a", 2.0, 0.2)
    el.record(ledger, today, "main", 5.0, 0.2)
    el.record(ledger, today - timedelta(days=1), "a", 1.0, 0.0)
    el.record(ledger, date(2025, 1, 1), "a", 9.0, 0.1)
    t = el.totals(ledger, today)
    assert t["today_kwh"] == 7.0 and t["today_cost"] == 1.4
    assert t["yesterday_kwh"] == 1.0 and t["yesterday_cost"] == 0
    assert t["month_kwh"] == 8.0 and t["year_kwh"] == 8.0
    assert el.totals(ledger, today, "main")["today_kwh"] == 5.0
    assert el.by_device(ledger, today, "month")[0] == ("main", 5.0, 1.0)
    days = el.daily(ledger, today, 3)
    assert [k for k, _ in days] == ["2026-11-03", "2026-11-04", "2026-11-05"] and days[-1][1] == 7.0
    el.prune(ledger, today, keep_days=30)
    assert "2025-01-01" not in ledger["days"]


def test_openmeteo_parse() -> None:
    js = {
        "utc_offset_seconds": 7200,
        "current": {"temperature_2m": 5.44, "weather_code": 61, "wind_speed_10m": 3.2},
        "hourly": {
            "time": ["2026-11-05T10:00", "2026-11-05T11:00"],
            "temperature_2m": [1.0, -2.0],
            "precipitation": [0.0, 0.4],
            "precipitation_probability": [10, 70],
            "weather_code": [3, 71],
        },
        "daily": {"time": ["2026-11-05"], "temperature_2m_max": [6], "temperature_2m_min": [-2], "weather_code": [3]},
    }
    fc = om.parse_forecast(js)
    assert fc["current"]["t"] == 5.4 and fc["current"]["cond"] == "rain"
    assert fc["hourly"][0]["ts"] == "2026-11-05T08:00:00+00:00" and fc["hourly"][1]["cond"] == "snow"
    assert fc["daily"][0]["ts"] == "2026-11-05" and fc["daily"][0]["min"] == -2
    now = datetime(2026, 11, 5, 8, 30, tzinfo=UTC)
    rows = om.window(fc["hourly"], 3, now)
    assert len(rows) == 2
    assert om.rain_expected(rows, 50) == (True, 0.4)
    assert om.rain_expected(rows, 80) == (False, 0.4)
    assert om.extreme(rows, "t", low=True) == -2.0
    air = om.parse_air(
        {
            "utc_offset_seconds": 0,
            "current": {"european_aqi": 70, "pm2_5": 12.3, "birch_pollen": 40, "grass_pollen": 80},
            "hourly": {"time": ["2026-11-05T10:00"], "european_aqi": [65], "birch_pollen": [5]},
        }
    )
    assert air["current"]["aqi"] == 70 and air["current"]["pollen"] == 80 and air["current"]["pollen_kind"] == "grass"
    assert air["hourly"][0]["pollen"] == 5
    assert "latitude=60.2055" in om.forecast_url(60.2055, 24.6559) and "wind_speed_unit=ms" in om.forecast_url(1, 2)
    demo_fc, demo_air = om.demo(now)
    assert demo_fc["current"]["t"] is not None and len(demo_fc["daily"]) == 4 and demo_air["current"]["aqi"]


def test_calendar_holidays() -> None:
    assert cl.easter_western(2026) == date(2026, 4, 5)
    assert cl.easter_western(2027) == date(2027, 3, 28)
    assert cl.easter_orthodox(2026) == date(2026, 4, 12)
    assert cl.easter_orthodox(2027) == date(2027, 5, 2)
    fi = cl.holidays("FI", 2026)
    assert fi[date(2026, 6, 19)]["local"] == "Juhannusaatto"
    assert fi[date(2026, 10, 31)]["local"] == "Pyhäinpäivä"
    assert fi[date(2026, 4, 3)]["en"] == "Good Friday"
    assert fi[date(2026, 5, 14)]["en"] == "Ascension Day"
    ua = cl.holidays("UA", 2026)
    assert ua[date(2026, 5, 31)]["uk"] == "Трійця" and date(2026, 12, 25) in ua and date(2026, 1, 7) not in ua
    w = cl.Workdays("FI", "auto", "2026-11-09..2026-11-10", "2026-11-07")
    assert not w.is_workday(date(2026, 12, 24)) and not w.is_workday(date(2026, 11, 8))
    assert not w.is_workday(date(2026, 11, 9)) and w.is_workday(date(2026, 11, 7)) and w.is_workday(date(2026, 11, 11))
    assert w.next_holiday(date(2026, 11, 5))[0] == date(2026, 12, 6)
    u = cl.Workdays("UA", "auto")
    assert u.is_workday(date(2026, 8, 24)) and u.holiday(date(2026, 8, 24))["en"] == "Independence Day"
    assert not cl.Workdays("UA", "yes").is_workday(date(2026, 8, 24))
    assert cl.parse_dates("2026-01-02, bad, 2026-01-05..2026-01-06") == {
        date(2026, 1, 2),
        date(2026, 1, 5),
        date(2026, 1, 6),
    }


ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:a
DTSTART;TZID=Europe/Helsinki:20261102T090000
DTEND;TZID=Europe/Helsinki:20261102T093000
RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=6
EXDATE;TZID=Europe/Helsinki:20261104T090000
SUMMARY:Stand\\, up
END:VEVENT
BEGIN:VEVENT
UID:b
DTSTART;VALUE=DATE:20261106
DTEND;VALUE=DATE:20261109
SUMMARY:Отпуск
END:VEVENT
BEGIN:VEVENT
UID:c
DTSTART:20261105T120000Z
DURATION:PT1H
SUMMARY:Call with a very long
  title
END:VEVENT
BEGIN:VEVENT
UID:d
STATUS:CANCELLED
DTSTART:20261105T120000Z
SUMMARY:Gone
END:VEVENT
BEGIN:VEVENT
UID:e
DTSTART;TZID=Europe/Helsinki:20200101T070000
DTEND;TZID=Europe/Helsinki:20200101T071500
RRULE:FREQ=DAILY
SUMMARY:Daily
END:VEVENT
BEGIN:VEVENT
UID:f
DTSTART:20261110T100000Z
DTEND:20261110T110000Z
RRULE:FREQ=MONTHLY;BYDAY=2TU
SUMMARY:Second tuesday
END:VEVENT
END:VCALENDAR
"""


def test_calendar_ics() -> None:
    ev = cl.parse_ics(ICS, HEL)
    assert {e["summary"] for e in ev} == {
        "Stand, up",
        "Отпуск",
        "Call with a very long title",
        "Daily",
        "Second tuesday",
    }
    start = datetime(2026, 11, 1, tzinfo=HEL)
    occ = cl.expand(ev, start, start + timedelta(days=30), HEL)
    stand = [o["start"].astimezone(HEL).strftime("%d %H:%M") for o in occ if o["title"] == "Stand, up"]
    assert stand == ["02 09:00", "09 09:00", "11 09:00", "16 09:00", "18 09:00"]
    assert len([o for o in occ if o["title"] == "Daily"]) == 30
    assert all(o["start"].astimezone(HEL).hour == 7 for o in occ if o["title"] == "Daily")
    assert len([o for o in occ if o["title"] == "Second tuesday"]) == 1
    vac = datetime(2026, 11, 7, 15, tzinfo=HEL)
    assert [o["title"] for o in cl.active(occ, vac)] == ["Отпуск"]
    assert cl.matches("Отпуск в Лапландии", "отпуск") and cl.matches("x", "") and not cl.matches("x", "y")
    day = [o["title"] for o in cl.on_day(occ, date(2026, 11, 5), HEL)]
    assert "Call with a very long title" in day and "Gone" not in day


def test_timers_parse() -> None:
    bad: list[str] = []
    ts = tl.parse_timers("Чайник=4\nСтирка = 90\nbad=x\nЧайник=5\nОкно", bad)
    assert bad == ["bad=x", "Чайник=5"]
    assert [(t["name"], t["minutes"]) for t in ts] == [("Чайник", 4.0), ("Стирка", 90.0), ("Окно", 10.0)]
    assert ts[0]["id"] == "t_chainyk"
    assert tl.parse_days("пн-пт") == ("days", {0, 1, 2, 3, 4})
    assert tl.parse_days("сб,нд") == ("days", {5, 6})
    assert tl.parse_days("пт-пн") == ("days", {4, 5, 6, 0})
    assert tl.parse_days("1 3 5") == ("days", {0, 2, 4})
    assert tl.parse_days("") == ("days", set(range(7)))
    assert tl.parse_days("рабочие") == ("work", set())
    assert tl.parse_days("когда-нибудь") is None
    bad = []
    al = tl.parse_alarms("Подъем=07:00 пн-пт\nПлохо=25:00\nВыходные=9:30 weekends\nбез времени", bad)
    assert bad == ["Плохо=25:00", "без времени"]
    assert [(a["name"], a["time"], a["days"]) for a in al] == [
        ("Подъем", "07:00", "пн-пт"),
        ("Выходные", "9:30", "weekends"),
    ]


def test_timers_schedule() -> None:
    weekdays = lambda d: d.weekday() < 5
    fri = datetime(2026, 11, 6, 7, 30, tzinfo=HEL)
    assert tl.next_alarm(fri, "07:00", "пн-пт", weekdays) == datetime(2026, 11, 9, 7, 0, tzinfo=HEL)
    assert tl.next_alarm(fri, "08:00", "пн-пт", weekdays) == datetime(2026, 11, 6, 8, 0, tzinfo=HEL)
    assert tl.next_alarm(fri, "09:00", "выходные", weekdays) == datetime(2026, 11, 7, 9, 0, tzinfo=HEL)
    assert tl.next_alarm(fri, "07:00", "рабочие", lambda d: d != date(2026, 11, 9) and d.weekday() < 5) == datetime(
        2026, 11, 10, 7, 0, tzinfo=HEL
    )
    assert tl.due(fri - timedelta(minutes=31), fri, "07:00", "пн-пт", weekdays)
    assert not tl.due(fri - timedelta(minutes=29), fri, "07:00", "пн-пт", weekdays)
    assert not tl.due(fri - timedelta(minutes=31), fri, "07:00", "сб", weekdays)
    assert tl.fmt_next(datetime(2026, 11, 9, 7, 0, tzinfo=HEL), fri, "ru") == "пн 07:00"
    assert tl.remaining_min(1000 + 61, 1000) == 2 and tl.remaining_min(None, 0) == 0


def test_timers_days_text() -> None:
    assert tl.fmt_days("сб,вс", "ru") == "сб, вс"
    assert tl.fmt_days("пн-пт", "ru") == "пн-пт"
    assert tl.fmt_days("mon,wed,fri", "en") == "Mon, Wed, Fri"
    assert tl.fmt_days("пн,вт,ср,пт", "uk") == "пн-ср, пт"
    assert tl.fmt_days("рабочие", "en") == "workdays"
    assert tl.fmt_days("", "ru") == "ежедневно"


@pytest.mark.parametrize(
    ("ext_id", "module"),
    [
        ("fi.valo.energy", "energy"),
        ("fi.valo.openmeteo", "openmeteo"),
        ("fi.valo.calendar", "workdays"),
        ("fi.valo.timers", "timers"),
        ("fi.valo.safety", "safety"),
        ("fi.valo.plugguard", "plugguard"),
    ],
)
def test_manifest_matches_module(
    ext_id: str, module: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pkg = PKGS / ext_id
    m = json.loads((pkg / "manifest.json").read_text("utf-8"))
    assert m["id"] == ext_id and m["module"] == module
    for lang in ("uk", "ru", "en"):
        text = (pkg / "docs" / f"{lang}.md").read_text("utf-8")
        assert "ё" not in text and "—" not in text
    catalog = json.loads((ROOT / "catalog.json").read_text("utf-8"))
    assert {"source": f"packages/{ext_id}"} in catalog
    defaults = {s["key"]: s.get("default") for s in m.get("settings", [])}
    monkeypatch.setenv("VALO_EXT_ID", ext_id)
    monkeypatch.setenv("VALO_EXT_DATA", str(tmp_path))
    monkeypatch.setenv("VALO_EXT_SETTINGS", json.dumps(defaults))
    sys.modules.pop(module, None)
    mod = importlib.import_module(module)
    ext = mod.ext
    for b in m.get("blocks", []):
        if b["kind"] != "trig":
            assert b["key"] in ext._blocks, b["key"]
    for p in m.get("pages", []) + m.get("widgets", []):
        assert p["key"] in ext._pages, p["key"]
    for tp in m.get("templates", []):
        for n in tp["graph"]["nodes"]:
            if n["block"].startswith(f"{ext_id}:"):
                assert any(b["key"] == n["block"].split(":", 1)[1] for b in m["blocks"])
    assert ext._devices
    for p in m.get("pages", []) + m.get("widgets", []):
        res = asyncio.run(ext._pages[p["key"]]({"lang": "ru"}))
        assert res["blocks"], p["key"]


def test_event_data_fills_empty_builtin_variables() -> None:
    from types import SimpleNamespace

    from app.domain import blocks

    home = SimpleNamespace(settings={"lang": "ru"}, name="Дом")
    flow = SimpleNamespace(id="f", name="Сценарий")
    run = blocks.Run(None, flow, None, True, home, HEL, None, {})
    tok = {"v": {"room": "Кухня", "date": "2026-11-06", "day": "06.11.2026", "count": 96}}
    text = asyncio.run(blocks.render(run, "{room} {day} {count} {date}", tok))
    room, day, count, today = text.split(" ")
    assert (room, day, count) == ("Кухня", "06.11.2026", "96")
    assert today == datetime.now(HEL).strftime("%d.%m.%Y")


def test_calendar_bad_events_are_skipped_one_by_one() -> None:
    text = ICS.replace("END:VCALENDAR", "") + (
        "BEGIN:VEVENT\nUID:x\nDTSTART:2026-11-01\nSUMMARY:Broken date\nEND:VEVENT\n"
        "BEGIN:VEVENT\nUID:y\nDTSTART:20261105T080000Z\nDTEND:20261105T090000Z\n"
        "RRULE:FREQ=DAILY;INTERVAL=x\nSUMMARY:Bad rule\nEND:VEVENT\n"
        "BEGIN:VEVENT\nUID:z\nDTSTART:20261105T100000Z\nDTEND:20261105T110000Z\n"
        "RRULE:FREQ=DAILY;UNTIL=bad\nSUMMARY:Bad until\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    stats: dict = {}
    ev = cl.parse_ics(text, HEL, stats)
    assert stats == {"skipped": 1, "unsupported": 3}
    start = datetime(2026, 11, 1, tzinfo=HEL)
    occ = cl.expand(ev, start, start + timedelta(days=30), HEL)
    titles = [o["title"] for o in occ]
    assert titles.count("Bad rule") == 1 and titles.count("Bad until") == 1 and "Broken date" not in titles
    assert titles.count("Daily") == 30


def test_sdk_rejects_invalid_command_as_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("VALO_EXT_ID", "test.ext")
    import valo_sdk

    ext = valo_sdk.Extension()
    sent: list = []

    async def pub(topic: str, payload: object, retain: bool = False, props: object = None) -> None:
        sent.append((topic, payload))

    monkeypatch.setattr(ext, "_pub", pub)

    def setter(values: dict) -> dict:
        raise ValueError("time must be HH:MM")

    ext.on_set("dev")(setter)
    with caplog.at_level("WARNING"):
        asyncio.run(ext._set("dev", {"cmd": "c1", "values": {"time": "25:00"}}))
    assert sent == [
        ("hub/v1/ext/test.ext/dev/dev/ack", {"cmd": "c1", "ok": False, "values": {}, "error": "time must be HH:MM"})
    ]
    assert any(r.levelname == "WARNING" for r in caplog.records)
    asyncio.run(ext.available("dev", False))
    assert sent[-1] == ("hub/v1/ext/test.ext/dev/dev/avail", "offline")


@pytest.mark.anyio
async def test_extension_device_takes_new_default_name_but_keeps_user_name(
    client: httpx.AsyncClient, owner: dict
) -> None:
    from app.db.base import commit, session
    from app.db.models import Device, Extension
    from app.domain import ingest

    async with session() as s:
        if await s.get(Extension, "fi.valo.test") is None:
            s.add(Extension(id="fi.valo.test", name="Test", version="1.0.0", trust="local", manifest={}))
        await commit(s)
    meta = {"name": "Calendar", "kind": "calendar", "caps": [{"id": "workday", "type": "bool", "access": "r"}]}
    for name in ("Calendar", "Календарь"):
        async with session() as s:
            await ingest.hub(s, "hub/v1/ext/fi.valo.test/dev/cal/meta", {**meta, "name": name})
            await commit(s)
    async with session() as s:
        d = await s.get(Device, "test-cal")
        assert d is not None and d.name == "Календарь"
    r = await client.patch("/api/v1/devices/test-cal", json={"name": "Мой календарь"}, headers=owner)
    assert r.status_code == 200, r.text
    async with session() as s:
        await ingest.hub(s, "hub/v1/ext/fi.valo.test/dev/cal/meta", {**meta, "name": "Kalender"})
        await commit(s)
    async with session() as s:
        assert (await s.get(Device, "test-cal")).name == "Мой календарь"


def test_openmeteo_places_and_shifted_demo() -> None:
    js = {
        "results": [
            {"name": "Lviv", "latitude": 49.83826, "longitude": 24.02324, "admin1": "Lviv", "country_code": "UA"},
            {"name": "", "latitude": 1, "longitude": 2},
            {"name": "Broken", "latitude": None, "longitude": 2},
        ]
    }
    assert om.parse_places(js) == [
        {"id": None, "name": "Lviv", "admin": "Lviv", "country": "UA", "lat": 49.8383, "lon": 24.0232}
    ]
    assert [p["name"] for p in om.demo_places("льв", "ru")] == ["Львов"]
    assert om.demo_places("", "ru") == []
    assert "language=uk" in om.geocode_url("Київ", "uk") and "name=" in om.geocode_url("Київ", "uk")
    now = datetime(2026, 11, 6, 12, tzinfo=UTC)
    base, _ = om.demo(now)
    warm, _ = om.demo(now, shift=5.0)
    assert round(warm["current"]["t"] - base["current"]["t"], 1) == 5.0


def test_openmeteo_search_in_several_languages_and_weather_look() -> None:
    assert om.search_langs("ru") == ["ru", "uk", "en"]
    assert om.search_langs("de") == ["de", "uk", "ru", "en"]
    a = {"id": 1, "name": "Ірпінь", "lat": 50.52, "lon": 30.25}
    b = {"id": 1, "name": "Irpin", "lat": 50.52, "lon": 30.25}
    c = {"id": None, "name": "X", "lat": 1.0, "lon": 2.0}
    assert om.merge_places([[], [a, c], [b, dict(c)]]) == [a, c]
    assert "id=707292" in om.place_url(707292, "ru") and "language=ru" in om.place_url(707292, "ru")
    assert om.look("clear", 1) == ("sun", "amber")
    assert om.look("clear", 0) == ("moon", "violet")
    assert om.look("partly", None) == ("cloud_sun", "amber")
    assert om.look("rain", 0) == ("rain", "frost")
    assert om.look("", 1) == ("cloud", "")
    assert {p["name"] for p in om.demo_places("ірпінь", "ru")} == {"Ирпень"}


def test_openmeteo_geocode_merges_languages_and_widget_blocks(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VALO_EXT_ID", "fi.valo.openmeteo")
    monkeypatch.setenv("VALO_EXT_DATA", str(tmp_path))
    monkeypatch.setenv("VALO_EXT_SETTINGS", json.dumps({"source": "api"}))
    monkeypatch.setenv("VALO_DEMO", "")
    sys.modules.pop("openmeteo", None)
    mod = importlib.import_module("openmeteo")
    found = {"uk": [{"id": 7, "name": "Ірпінь", "latitude": 50.5218, "longitude": 30.2506, "admin1": "Київська"}]}

    def fake(url: str) -> dict:
        if "/v1/get" in url:
            return {"id": 7, "name": "Ирпень", "latitude": 50.5218, "longitude": 30.2506, "admin1": "Киевская"}
        if "language=en" in url:
            raise OSError("offline")
        lang = url.split("language=")[1].split("&")[0]
        return {"results": found.get(lang, [])}

    monkeypatch.setattr(mod, "get_json", fake)
    res = asyncio.run(mod.page_geocode({"q": "Ірпінь", "lang": "ru"}))
    assert res["places"] == [
        {"id": 7, "name": "Ирпень", "admin": "Киевская", "country": "", "lat": 50.5218, "lon": 30.2506}
    ]
    mod.data["fc"], _ = om.demo(datetime.now(UTC))
    blocks = asyncio.run(mod.page_now({"lang": "ru"}))["blocks"]
    assert [b["type"] for b in blocks] == ["hero", "strip"]
    assert (
        blocks[0]["icon"] in {"cloud_sun", "cloud_moon", "rain"}
        and blocks[0]["value"] == mod.data["fc"]["current"]["t"]
    )
    strip = blocks[1]["items"]
    assert len(strip) == 8 and strip[0]["label"]["ru"] == "Сейчас" and all(i["unit"] == "°" for i in strip)


def fake_core(mod, monkeypatch: pytest.MonkeyPatch, devices: list[dict]) -> dict[str, list]:
    rec: dict[str, list] = {"calls": [], "triggers": [], "states": []}

    async def call(method: str, params: dict | None = None, timeout: float = 10) -> object:
        rec["calls"].append((method, params or {}))
        if method == "devices.list":
            return devices
        if method == "rooms":
            return [{"id": "bath", "name": "Ванная", "floor": 1}]
        if method == "home":
            return {"timezone": "Europe/Helsinki", "lang": "ru"}
        return {"ok": True}

    async def trigger(key: str, payload: object = None) -> None:
        rec["triggers"].append((key, payload))

    async def state(dev: str, values: dict) -> None:
        rec["states"].append((dev, values))

    async def changed(*keys: str) -> None:
        return None

    monkeypatch.setattr(mod.ext, "call", call)
    monkeypatch.setattr(mod.ext, "trigger", trigger)
    monkeypatch.setattr(mod.ext, "state", state)
    monkeypatch.setattr(mod.ext, "changed", changed)
    mod.ext.lang = "ru"
    return rec


def load_ext(module: str, ext_id: str, settings: dict, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VALO_EXT_ID", ext_id)
    monkeypatch.setenv("VALO_EXT_DATA", str(tmp_path))
    monkeypatch.setenv("VALO_EXT_SETTINGS", json.dumps(settings))
    sys.modules.pop(module, None)
    return importlib.import_module(module)


LEAK = {"id": "leak1", "name": "Протечка ванной", "roomId": "bath", "available": True, "lastSeen": None}
LEAK_CAPS = [{"id": "leak", "type": "bool", "access": "r"}, {"id": "bat", "type": "num", "access": "r"}]
SMOKE_CAPS = [{"id": "smoke", "type": "bool", "access": "r"}, {"id": "test", "type": "bool", "access": "r"}]


def test_safety_finds_sensors_and_ignores_untrusted_values() -> None:
    devs = [
        LEAK | {"caps": LEAK_CAPS, "state": {"leak": False, "bat": 88}},
        {"id": "smoke1", "name": "Дым", "caps": SMOKE_CAPS, "state": {}},
        {"id": "plug", "name": "Розетка", "caps": [{"id": "on", "type": "bool", "access": "rw"}], "state": {}},
        {"id": "safety", "extId": "fi.valo.safety", "caps": LEAK_CAPS, "state": {}},
        {"id": "skip", "caps": LEAK_CAPS, "state": {}},
        "garbage",
    ]
    found = sl.sensors(devs, "fi.valo.safety", {"skip"})
    assert [d["id"] for d in found] == ["leak1", "smoke1"]
    s = sl.sensor(found[0])
    assert s is not None and s["kinds"] == ["leak"] and s["bat"] == 88 and s["room"] == "bath"
    assert sl.apply(s, {"leak": "true", "bat": "5"}, 0) == ([], []) and s["bat"] == 88
    assert sl.apply(s, {"leak": True, "bat": float("nan")}, 0) == (["leak"], []) and s["bat"] == 88
    assert sl.apply(s, {"leak": True}, 1) == ([], [])
    assert sl.apply(s, {"leak": False}, 2) == ([], ["leak"])
    assert sl.apply(s, "x", 3) == ([], [])
    assert sl.parse_ids("pump, boiler\nvalve;pump") == ["pump", "boiler", "valve"]
    assert sl.num(True) is None and sl.num(float("inf")) is None and sl.num(3) == 3.0


def test_safety_incidents_alarm_and_smoke_test() -> None:
    s = sl.sensor({"id": "smoke1", "name": "Дым", "caps": SMOKE_CAPS, "state": {}})
    assert s is not None
    incs: list = []
    sl.apply(s, {"test": True, "smoke": True}, 100)
    assert sl.is_test(s, "smoke", 150) and not sl.is_test(s, "smoke", 100 + sl.TEST_GRACE_S + 1)
    sl.open_incident(incs, s, "smoke", 100, test=True)
    assert not sl.alarm_on(incs, [s], 150)
    assert sl.alarm_on(incs, [s], 100 + sl.TEST_GRACE_S + 1)
    sl.apply(s, {"smoke": False}, 200)
    assert sl.close_incidents(incs, "smoke1", "smoke", 200) == 1 and incs[0]["end"] == 200
    sl.apply(s, {"smoke": True}, 1000)
    sl.open_incident(incs, s, "smoke", 1000)
    sl.apply(s, {"smoke": False}, 1010)
    assert sl.alarm_on(incs, [s], 1010)
    assert sl.ack(incs) == 1 and not sl.alarm_on(incs, [s], 1010)
    for i in range(sl.MAX_INCIDENTS + 5):
        sl.open_incident(incs, s, "smoke", 2000 + i)
    assert len(incs) == sl.MAX_INCIDENTS and incs[-1]["id"] == sl.MAX_INCIDENTS + 7
    bad = [{"kind": "fire", "ts": 1}, {"kind": "leak", "ts": "x"}, "x", {"kind": "leak", "ts": 5, "shutoff": "pump"}]
    assert sl.restore(bad) == [{"kind": "leak", "ts": 5, "shutoff": []}] and sl.restore({"a": 1}) == []


def test_safety_reminders() -> None:
    today = date(2026, 11, 6)
    assert sl.test_due(None, today, 30) and sl.test_due("bad", today, 30)
    assert not sl.test_due("2026-10-20", today, 30) and sl.test_due("2026-10-07", today, 30)
    assert sl.remind(None, None, today, 30) and not sl.remind(None, "2026-11-03", today, 30)
    assert sl.remind(None, "2026-10-30", today, 30) and not sl.remind("2026-11-01", None, today, 30)
    s = {"id": "a", "name": "A", "kinds": ["leak"], "state": {}, "available": False, "bat": 12.0}
    assert [k for k, _ in sl.warnings([s])] == ["offline", "battery"]
    assert sl.seen_text("2026-11-06T08:05:00+00:00", HEL, datetime(2026, 11, 6, 12, tzinfo=HEL)) == "10:05"
    assert sl.seen_text("2026-11-01T08:05:00+00:00", HEL, datetime(2026, 11, 6, 12, tzinfo=HEL)) == "01.11 10:05"
    assert sl.seen_text("nonsense", HEL, datetime(2026, 11, 6, tzinfo=HEL)) == ""


def test_safety_leak_switches_off_when_armed(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = load_ext("safety", "fi.valo.safety", {"shutoff": "pump", "test_days": 30}, tmp_path, monkeypatch)
    devices = [
        LEAK | {"caps": LEAK_CAPS, "state": {"leak": False, "bat": 15}},
        {"id": "pump", "name": "Насос", "caps": [{"id": "on", "type": "bool", "access": "rw"}], "state": {"on": True}},
    ]
    rec = fake_core(mod, monkeypatch, devices)

    async def run() -> None:
        await mod.start()
        assert list(mod.sens) == ["leak1"] and mod.values()["warnings"] == 1
        await mod.on_state("hub/v1/core/state/leak1", {"leak": True})
        cmds = [p for m, p in rec["calls"] if m == "devices.command"]
        assert cmds == [{"id": "pump", "values": {"on": False}}]
        note = next(p for m, p in rec["calls"] if m == "notify")
        assert note["level"] == "crit" and "Протечка ванной, Ванная" in note["text"] and "Насос" in note["text"]
        key, payload = rec["triggers"][-1]
        assert key == "alarm" and payload["kind"] == "leak" and payload["device"] == "leak1"
        assert payload["shutoff"] == "Насос" and payload["room"] == "Ванная"
        assert rec["states"][-1][1]["alarm"] is True
        hero = (await mod.page_status({"lang": "ru"}))["blocks"][0]
        assert hero["tone"] == "crit" and hero["icon"] == "warn" and hero["value"] == 1
        await mod.page_safety({"action": "ack"})
        assert mod.values()["alarm"] is True
        await mod.on_state("hub/v1/core/state/leak1", {"leak": False})
        assert mod.values()["alarm"] is False and mod.incidents[-1]["end"] is not None
        await mod.page_safety({"action": "disarm"})
        await mod.on_state("hub/v1/core/state/leak1", {"leak": True})
        assert len([1 for m, _ in rec["calls"] if m == "devices.command"]) == 1
        saved = json.loads((tmp_path / "state.json").read_text("utf-8"))
        assert saved["armed"] is False and saved["active"] == {"leak1": ["leak"]} and len(saved["incidents"]) == 2

    asyncio.run(run())
    mod2 = load_ext("safety", "fi.valo.safety", {"shutoff": "pump"}, tmp_path, monkeypatch)
    rec2 = fake_core(mod2, monkeypatch, devices)
    devices[0]["state"]["leak"] = True
    asyncio.run(mod2.start())
    assert not [1 for m, _ in rec2["calls"] if m == "notify"] and mod2.st["armed"] is False


def plug(did: str, w: float | None, on: bool = True, kwh: float | None = None) -> dict:
    caps = [{"id": "on", "type": "bool", "access": "rw"}, {"id": "w", "type": "num", "access": "r"}]
    st: dict = {"on": on, "w": w}
    if kwh is not None:
        caps.append({"id": "kwh", "type": "num", "access": "r"})
        st["kwh"] = kwh
    return {"id": did, "name": did.title(), "caps": caps, "state": st, "available": True}


def test_plugguard_overload_and_standby() -> None:
    devs = [
        plug("a", 10),
        {"id": "meter", "caps": [{"id": "w", "type": "num", "access": "r"}], "state": {"w": 5000}},
        {"id": "ro", "caps": [{"id": "on", "access": "r"}, {"id": "w"}], "state": {}},
        plug("own", 1) | {"extId": "fi.valo.plugguard"},
        None,
    ]
    assert [d["id"] for d in pl.plugs(devs, "fi.valo.plugguard")] == ["a"]
    w = pl.watch(plug("a", 3000))
    assert not pl.overload(w, 0, 2500, 10) and not pl.overload(w, 9, 2500, 10)
    assert pl.overload(w, 10, 2500, 10)
    pl.tripped(w, 10)
    assert not pl.overload(w, 21, 2500, 10) and pl.overload(w, 41, 2500, 10)
    pl.update(w, {"w": 100})
    assert not pl.overload(w, 50, 2500, 10) and w["over_since"] is None
    pl.update(w, {"w": "5000", "on": "off"})
    assert w["w"] == 100 and w["on"] is True
    pl.update(w, {"w": 3000, "on": False})
    assert not pl.overload(w, 60, 2500, 0)
    s = pl.watch(plug("b", 1.5))
    assert not pl.standby(s, 0, 3, 30) and not pl.standby(s, 1799, 3, 30) and pl.standby(s, 1800, 3, 30)
    pl.update(s, {"w": 40})
    assert not pl.standby(s, 1900, 3, 30) and s["low_since"] is None


def test_plugguard_daily_ledger() -> None:
    day = date(2026, 11, 6)
    led: dict = {}
    assert pl.roll(led, day) and pl.valid(led) and not pl.roll(led, day)
    w = pl.watch(plug("a", 1000))
    pl.advance(led, w, 0, 8)
    assert pl.advance(led, w, 3.6, 8) == pytest.approx(0.001)
    assert pl.advance(led, w, 3600, 9) == 0
    assert led["plugs"]["a"]["peak"] == 1000 and led["plugs"]["a"]["on_s"] == 3.6
    c = pl.watch(plug("c", 50, kwh=10.0))
    assert pl.advance(led, c, 1, 9) == 0
    pl.update(c, {"kwh": 10.25})
    assert pl.advance(led, c, 1, 9) == pytest.approx(0.25)
    pl.update(c, {"kwh": 0.1})
    assert pl.advance(led, c, 1, 10) == pytest.approx(0.1)
    pl.update(c, {"kwh": 500.0})
    assert pl.advance(led, c, 1, 10) == 0
    assert led["hours"][8] == pytest.approx(0.001) and led["hours"][9] == pytest.approx(0.25)
    assert pl.total_kwh(led) == pytest.approx(0.351)
    assert pl.roll(led, day + timedelta(days=1))
    assert led["plugs"] == {} and sum(led["hours"]) == 0 and led["meters"]["c"]["last_kwh"] == 500.0
    assert pl.yesterday_kwh(led, day + timedelta(days=1)) == pytest.approx(0.351)
    assert not pl.valid({"day": "2026-11-06", "plugs": {}, "hours": [0] * 23}) and not pl.valid([])
    assert not pl.valid(led | {"history": {"2026-11-05": {"a": "1"}}})
    assert not pl.valid(led | {"plugs": {"a": {"kwh": None}}}) and pl.valid(json.loads(json.dumps(led)))


class Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def time(self) -> float:
        return self.t


def test_plugguard_switches_off_overloaded_plug(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = {"limit_w": 2000, "delay_s": 10, "standby": "tv", "standby_w": 3, "standby_min": 1}
    mod = load_ext("plugguard", "fi.valo.plugguard", settings, tmp_path, monkeypatch)
    devices = [plug("kettle", 100, kwh=1.0), plug("tv", 1.0)]
    rec = fake_core(mod, monkeypatch, devices)
    clock = Clock(1_000_000.0)
    monkeypatch.setattr(mod, "time", clock)

    async def run() -> None:
        await mod.start()
        assert set(mod.watches) == {"kettle", "tv"}
        await mod.tick()
        await mod.on_state("hub/v1/core/state/kettle", {"w": 2400, "kwh": 1.2})
        for dt in (1, 5, 11):
            clock.t = 1_000_000.0 + dt
            await mod.tick()
        cmds = [p for m, p in rec["calls"] if m == "devices.command"]
        assert cmds == [{"id": "kettle", "values": {"on": False}}]
        assert rec["triggers"][0] == ("overload", {"device": "kettle", "name": "Kettle", "w": 2400, "limit": 2000})
        note = next(p for m, p in rec["calls"] if m == "notify")
        assert note["level"] == "warn" and "Kettle" in note["text"]
        assert mod.ledger["plugs"]["kettle"]["trips"] == 1
        assert mod.ledger["plugs"]["kettle"]["kwh"] == pytest.approx(0.2)
        clock.t = 1_000_000.0 + 61
        await mod.tick()
        assert ("devices.command", {"id": "tv", "values": {"on": False}}) in rec["calls"]
        assert rec["triggers"][-1][0] == "standby_off"
        res = await mod.b_power_above({"device": "kettle", "value": 1000}, {}, False)
        assert res["outs"] == [[0, {"power": 2400, "plug": "Kettle"}]]
        res = await mod.b_power_above({"device": "kettle", "value": 5000}, {}, False)
        assert res["outs"] == [[1]]
        blocks = (await mod.page_plugs({"lang": "ru"}))["blocks"]
        assert [b["type"] for b in blocks] == ["hero", "bars", "list", "text"]
        assert blocks[0]["unit"] == "W" and blocks[2]["items"][0]["text"] == "Kettle"
        await mod.page_plugs({"action": "off:tv"})
        with pytest.raises(ValueError):
            await mod.page_plugs({"action": "off:unknown"})
        widget = (await mod.page_now({"lang": "ru"}))["blocks"]
        assert [b["type"] for b in widget] == ["hero", "list"] and len(widget[1]["items"]) <= 3

    asyncio.run(run())
    mod.save()
    again = load_ext("plugguard", "fi.valo.plugguard", settings, tmp_path, monkeypatch)
    assert again.ledger["plugs"]["kettle"]["kwh"] == pytest.approx(0.2)
