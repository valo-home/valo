import asyncio
import importlib
import io
import json
import pathlib
import sys
import time

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "extensions" / "packages" / "fi.valo.vision"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "extensions" / "sdk"))
import visionlogic as vl

PKG = pathlib.Path(__file__).resolve().parents[2] / "extensions" / "packages" / "fi.valo.vision"
SQUARE = [[0.0, 0.5], [1.0, 0.5], [1.0, 1.0], [0.0, 1.0]]


def test_point_in_polygon_and_zones() -> None:
    assert vl.inside((0.5, 0.75), SQUARE)
    assert not vl.inside((0.5, 0.25), SQUARE)
    tri = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    assert vl.inside((0.2, 0.2), tri) and not vl.inside((0.8, 0.8), tri)
    box = (0.4, 0.2, 0.6, 0.8)
    assert vl.zone_of(box, []) == ""
    assert vl.zone_of(box, [{"id": "yard", "kind": "include", "points": SQUARE}]) == "yard"
    assert vl.zone_of((0.4, 0.1, 0.6, 0.3), [{"id": "yard", "kind": "include", "points": SQUARE}]) is None
    assert vl.zone_of(box, [{"id": "street", "kind": "exclude", "points": SQUARE}]) is None
    both = [{"id": "street", "kind": "exclude", "points": SQUARE}, {"id": "all", "kind": "include", "points": tri}]
    assert vl.zone_of((0.1, 0.1, 0.2, 0.3), both) == "all"


def test_nms_keeps_best_per_class() -> None:
    a = (0, 0.9, [0.1, 0.1, 0.5, 0.5])
    b = (0, 0.6, [0.12, 0.12, 0.52, 0.52])
    c = (2, 0.7, [0.12, 0.12, 0.52, 0.52])
    d = (0, 0.5, [0.6, 0.6, 0.9, 0.9])
    out = vl.nms([b, a, c, d])
    assert out == [a, c, d]
    assert vl.iou([0, 0, 1, 1], [0, 0, 1, 1]) == 1.0
    assert vl.iou([0, 0, 0.5, 0.5], [0.5, 0.5, 1, 1]) == 0.0


def test_decode_raw_output() -> None:
    p = np.zeros((1, 3549, 85), np.float32)
    idx = 52 * 52 + 26 * 26 + 6 * 13 + 6
    p[0, idx, :4] = [0.5, 0.5, np.log(4.0), np.log(8.0)]
    p[0, idx, 4] = 0.9
    p[0, idx, 5] = 0.95
    res = vl.decode(p, 416 / 832, 832, 832, 0.5)
    assert len(res) == 1
    cls, score, box = res[0]
    assert cls == 0 and score == pytest.approx(0.855, abs=1e-3)
    cx, cy = (6.5 * 32) / (416 / 832) / 832, (6.5 * 32) / (416 / 832) / 832
    assert (box[0] + box[2]) / 2 == pytest.approx(cx, abs=1e-4)
    assert (box[1] + box[3]) / 2 == pytest.approx(cy, abs=1e-4)
    assert box[2] - box[0] == pytest.approx(128 * 2 / 832, abs=1e-4)
    assert box[3] - box[1] == pytest.approx(256 * 2 / 832, abs=1e-4)
    assert vl.decode(p, 0.5, 832, 832, 0.9) == []


def test_select_labels_threshold_and_merge() -> None:
    raw = [
        (16, 0.8, [0.1, 0.5, 0.3, 0.9]),
        (15, 0.6, [0.11, 0.5, 0.31, 0.9]),
        (0, 0.5, [0.5, 0.2, 0.6, 0.9]),
        (2, 0.9, [0.6, 0.1, 0.9, 0.3]),
        (60, 0.99, [0.0, 0.0, 1.0, 1.0]),
    ]
    dets = vl.select(raw, {"labels": ["person", "animal"], "score": 0.45}, [])
    assert sorted((d.label, round(d.score, 2)) for d in dets) == [("animal", 0.8), ("person", 0.5)]
    dets = vl.select(raw, {"labels": [], "score": 0.55}, [{"id": "low", "kind": "include", "points": SQUARE}])
    assert [d.label for d in dets] == ["animal"] and dets[0].zone == "low"
    assert dets[0].view()["box"] == [0.1, 0.5, 0.3, 0.9]


def test_tracker_start_and_end() -> None:
    t = vl.Tracker(hold=5)
    person = vl.Det("person", 0.7, (0, 0, 1, 1))
    started, ended = t.step([person, vl.Det("person", 0.9, (0, 0, 1, 1))], 0)
    assert [d.score for d in started] == [0.9] and ended == []
    assert t.step([person], 2) == ([], [])
    assert t.step([], 6) == ([], [])
    assert t.step([], 7.5) == ([], ["person"])
    t.step([vl.Det("car", 0.6, (0, 0, 1, 1))], 8)
    assert t.close() == ["car"] and not t.active


def test_draw_and_model() -> None:
    buf = io.BytesIO()
    Image.new("RGB", (640, 360), (90, 90, 90)).save(buf, "JPEG")
    out = vl.draw(buf.getvalue(), [vl.Det("person", 0.81, (0.2, 0.2, 0.5, 0.9))])
    img = Image.open(io.BytesIO(out))
    assert img.format == "JPEG" and img.size == (640, 360)
    assert img.getpixel((int(0.2 * 640) + 1, 250)) != (90, 90, 90)
    vl.verify()
    det = vl.Detector()
    assert vl.select(det.run(buf.getvalue()), {"labels": [], "score": 0.5}, []) == []


def test_manifest_and_module(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m = json.loads((PKG / "manifest.json").read_text("utf-8"))
    assert m["id"] == "fi.valo.vision" and m["module"] == "vision"
    assert {"cameras.stream", "cameras.events", "media.write", "devices.read"} <= set(m["perms"])
    assert len(m["name"]) == 7 and len(m["description"]) == 7
    for lang in ("uk", "ru", "en"):
        text = (PKG / "docs" / f"{lang}.md").read_text("utf-8")
        assert "ё" not in text and "—" not in text
    catalog = json.loads((PKG.parents[1] / "catalog.json").read_text("utf-8"))
    assert {"source": "packages/fi.valo.vision"} in catalog
    monkeypatch.setenv("VALO_EXT_ID", "fi.valo.vision")
    monkeypatch.setenv("VALO_EXT_DATA", str(tmp_path))
    monkeypatch.setenv("VALO_EXT_SETTINGS", json.dumps({s["key"]: s["default"] for s in m["settings"]}))
    sys.modules.pop("vision", None)
    mod = importlib.import_module("vision")
    assert "hub/v1/core/state/+" in mod.ext._subs
    assert mod.setting("fps", 1, 0.2, 4) == 1
    monkeypatch.setitem(mod.ext.settings, "fps", "x")
    assert mod.setting("fps", 1, 0.2, 4) == 1


def test_watch_reports_events(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VALO_EXT_ID", "fi.valo.vision")
    monkeypatch.setenv("VALO_EXT_DATA", str(tmp_path))
    monkeypatch.setenv("VALO_EXT_SETTINGS", json.dumps({"fps": 4, "hold_s": 2, "max_s": 10}))
    sys.modules.pop("vision", None)
    mod = importlib.import_module("vision")
    buf = io.BytesIO()
    Image.new("RGB", (320, 180), (40, 40, 40)).save(buf, "JPEG")
    seen = {"n": 0}
    calls: list[tuple] = []

    class Fake:
        def run(self, data: bytes) -> list:
            seen["n"] += 1
            return [(0, 0.8, [0.4, 0.3, 0.6, 0.9])] if seen["n"] <= 2 else []

    async def frame(cid: str, sub: bool = True, fresh: bool = False) -> bytes:
        return buf.getvalue()

    async def event(cid: str, label: str, active: bool | None, score: float | None = None, data: dict | None = None):
        calls.append(("event", cid, label, active))
        return {"ok": True, "event": 7}

    async def put(cid: str, data: bytes, event: int | None = None, label: str = "", meta: dict | None = None):
        calls.append(("media", cid, event, label, data[:2]))
        return {"id": "m"}

    monkeypatch.setattr(mod, "detector", Fake())
    monkeypatch.setattr(mod.ext, "camera_frame", frame)
    monkeypatch.setattr(mod.ext, "camera_event", event)
    monkeypatch.setattr(mod.ext, "media_put", put)
    mod.cams["c"] = {"id": "c", "detect": {"enabled": True, "labels": ["person"], "score": 0.5}, "zones": []}
    mod.moving["c"] = False
    mod.until["c"] = time.monotonic() + 3
    asyncio.run(mod.watch("c"))
    assert calls[0] == ("event", "c", "person", True)
    assert calls[1] == ("media", "c", 7, "person", b"\xff\xd8")
    assert calls[-1] == ("event", "c", "person", False)
    assert sum(1 for c in calls if c[0] == "event" and c[3] is False) == 1
