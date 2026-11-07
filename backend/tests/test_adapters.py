import pytest

from app.domain import adapters
from app.lib.errors import ApplicationError

ON = {"type": "binary", "name": "state", "property": "state", "access": 7, "value_on": "ON", "value_off": "OFF"}


def sw(ep: str) -> dict:
    return {"type": "switch", "endpoint": ep, "features": [{**ON, "property": f"state_{ep}", "endpoint": ep}]}


def test_multi_gang_switch_keeps_channels() -> None:
    caps, conv = adapters.z2m_caps([sw("l1"), sw("l2"), {"type": "numeric", "property": "linkquality", "access": 1}])
    ids = [c["id"] for c in caps]
    assert ids == ["on_l1", "on_l2", "lqi"]
    assert adapters.kind_of(caps) == "switch"
    assert adapters.z2m_in(conv, {"state_l1": "ON", "state_l2": "OFF"}) == {"on_l1": True, "on_l2": False}
    assert adapters.z2m_out(conv, {"on_l2": True}) == {"state_l2": "ON"}


def test_rgb_light_color_xy_and_hs() -> None:
    exposes = [
        {
            "type": "light",
            "features": [
                ON,
                {"type": "numeric", "property": "brightness", "access": 7, "value_min": 0, "value_max": 254},
                {"type": "composite", "name": "color_xy", "property": "color", "access": 7, "features": []},
                {"type": "composite", "name": "color_hs", "property": "color", "access": 7, "features": []},
            ],
        }
    ]
    caps, conv = adapters.z2m_caps(exposes)
    by = {c["id"]: c for c in caps}
    assert by["color"] == {"id": "color", "type": "color", "access": "rw"}
    assert [c["id"] for c in caps].count("color") == 1
    assert adapters.kind_of(caps) == "light"
    red = adapters.z2m_in(conv, {"color": {"x": 0.7006, "y": 0.2993}})["color"]
    assert red.startswith("#ff") and int(red[3:5], 16) < 40
    assert adapters.color_hex({"hue": 120, "saturation": 100}) == "#00ff00"
    assert adapters.color_hex({"hex": "#AABBCC"}) == "#aabbcc"
    assert adapters.color_hex({"x": 0.3, "y": 0}) is None
    assert adapters.z2m_out(conv, {"color": "#00ff00"}) == {"color": {"hex": "#00ff00"}}
    assert adapters.validate(by["color"], "#00FF00") == "#00ff00"
    with pytest.raises(ApplicationError):
        adapters.validate(by["color"], "green")


def test_lock_and_fan() -> None:
    lock = [{"type": "lock", "features": [{**ON, "value_on": "LOCK", "value_off": "UNLOCK"}]}]
    caps, conv = adapters.z2m_caps(lock)
    assert [c["id"] for c in caps] == ["locked"] and adapters.kind_of(caps) == "lock"
    assert adapters.z2m_out(conv, {"locked": True}) == {"state": "LOCK"}
    fan = [
        {
            "type": "fan",
            "features": [
                ON,
                {"type": "enum", "property": "fan_mode", "name": "mode", "access": 7, "values": ["low", "high"]},
            ],
        }
    ]
    caps, _ = adapters.z2m_caps(fan)
    assert {c["id"] for c in caps} == {"on", "fan_mode"} and adapters.kind_of(caps) == "fan"
    child = [{"type": "binary", "property": "child_lock", "access": 3, "value_on": "LOCK", "value_off": "UNLOCK"}]
    assert adapters.kind_of(adapters.z2m_caps(child)[0]) != "lock"
