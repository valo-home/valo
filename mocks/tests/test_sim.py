import asyncio
import json
import pathlib
import unittest

from valo_mocks import sim

SCENARIO = json.loads((pathlib.Path(sim.__file__).with_name("scenario.json")).read_text("utf-8"))


class ScenarioTest(unittest.TestCase):
    def test_devices_are_consistent(self) -> None:
        zig = SCENARIO["zigbee"]
        self.assertEqual(len(zig), 38)
        self.assertEqual(len({d["ieee"] for d in zig}), len(zig))
        self.assertEqual(len({d["key"] for d in zig}), len(zig))
        rooms = {r["id"] for r in SCENARIO["rooms"]}
        for d in zig:
            self.assertIn(d["kind"], sim.EXPOSES, d["key"])
            if d.get("room"):
                self.assertIn(d["room"], rooms, d["key"])

    def test_owner_and_home(self) -> None:
        self.assertEqual(SCENARIO["owner"]["username"], "mikko")
        self.assertTrue(SCENARIO["home"]["timezone"])


class ConvertTest(unittest.TestCase):
    def test_values_to_z2m(self) -> None:
        self.assertEqual(sim.z2m("light", {"on": True, "bri": 50}), {"state": "ON", "brightness": 127})
        self.assertEqual(
            sim.z2m("trv", {"t": 20.5, "sp": 21}), {"local_temperature": 20.5, "occupied_heating_setpoint": 21}
        )
        self.assertEqual(sim.z2m("contact", {"open": True}), {"contact": False})

    def test_props_flatten_features(self) -> None:
        items = [{"type": "light", "features": [sim.b("state", 7, "ON", "OFF"), sim.n("brightness", 7, lo=0, hi=254)]}]
        self.assertEqual(set(sim.props(items)), {"state", "brightness"})
        self.assertIn("state", sim.WRITABLE["light_ct"])


class SimTest(unittest.TestCase):
    def setUp(self) -> None:
        self.s = sim.Sim(json.loads(json.dumps(SCENARIO)))

    def test_bridge_items_look_like_z2m(self) -> None:
        for d in self.s.active():
            it = self.s.item(d)
            self.assertEqual(it["ieee_address"], d["ieee"])
            self.assertIn(it["type"], ("Router", "EndDevice"))
            if self.s.supported(d):
                self.assertTrue(it["definition"]["exposes"])
        info = self.s.info()
        self.assertIn("coordinator", info)
        self.assertEqual(info["network"]["channel"], self.s.sc["coordinator"]["channel"])

    def test_rgb_and_two_gang(self) -> None:
        rgb = next(d for d in self.s.active() if d["kind"] == "light_rgb")
        self.assertEqual(rgb["st"]["color"], {"hex": "#ff8a3d"})
        self.assertIn("color", sim.WRITABLE["light_rgb"])
        gang = next(d for d in self.s.active() if d["kind"] == "relay2")
        self.assertEqual((gang["st"]["state_l1"], gang["st"]["state_l2"]), ("ON", "OFF"))
        self.assertEqual(sim.WRITABLE["relay2"], {"state_l1", "state_l2"})

    def test_set_updates_state_and_publishes(self) -> None:
        sent: list[tuple[str, object]] = []

        async def pub(topic: str, payload: object, retain: bool = False) -> None:
            sent.append((topic, payload))

        self.s.pub = pub  # type: ignore[method-assign]
        light = next(d for d in self.s.active() if d["kind"] == "light_ct" and not d["offline"])
        asyncio.run(self.s.on_set(light["fn"], {"state": "ON", "brightness": 254}))
        self.assertEqual(light["st"]["state"], "ON")
        self.assertTrue(any(t == f"{sim.Z}/{light['fn']}" for t, _ in sent))


if __name__ == "__main__":
    unittest.main()
