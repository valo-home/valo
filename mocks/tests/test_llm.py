import json
import unittest

from valo_mocks import llm


class DemoModelTest(unittest.TestCase):
    def test_overview_calls_tool_then_answers(self) -> None:
        msgs = [{"role": "system", "content": "x"}, {"role": "user", "content": "Что дома?"}]
        self.assertEqual(llm.plan(msgs), ("tool", ("home_overview", {})))
        msgs += [
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c", "function": {"name": "home_overview"}}]},
            {
                "role": "tool",
                "content": json.dumps({"home": "Дом", "devices": 3, "rooms": [1], "offline": [], "alarms": []}),
            },
        ]
        kind, text = llm.plan(msgs)
        self.assertEqual(kind, "text")
        self.assertIn("**Дом**", text)
        self.assertIn("3", text)

    def test_voltage_dashboard_uses_plug_with_voltage(self) -> None:
        msgs = [{"role": "user", "content": "Make a dashboard with plug voltage"}]
        self.assertEqual(llm.plan(msgs)[1][0], "list_devices")
        plugs = {
            "devices": [
                {"id": "p0", "name": "No v", "state": {"w": 1}},
                {"id": "p1", "name": "Kettle", "state": {"v": 230}},
            ]
        }
        msgs += [{"role": "assistant", "content": None}, {"role": "tool", "content": json.dumps(plugs)}]
        kind, (name, args) = llm.plan(msgs)
        self.assertEqual((kind, name), ("tool", "create_dashboard"))
        self.assertEqual(args["widgets"][0], {"type": "chart", "device": "p1", "cap": "v", "hours": 24, "size": "wide"})
        msgs += [
            {"role": "assistant", "content": None},
            {"role": "tool", "content": json.dumps({"ok": True, "result": {"name": "Voltage"}})},
        ]
        self.assertIn("Kettle", llm.plan(msgs)[1])

    def test_named_plug_and_batteries(self) -> None:
        msgs = [{"role": "user", "content": "Make a dashboard with the voltage of the PC plug"}]
        plugs = {
            "devices": [
                {"id": "p1", "name": "Kettle", "state": {"v": 230}},
                {"id": "p2", "name": "PC plug", "state": {"v": 229}},
            ]
        }
        msgs += [{"role": "assistant", "content": None}, {"role": "tool", "content": json.dumps(plugs)}]
        self.assertEqual(llm.plan(msgs)[1][1]["widgets"][0]["device"], "p2")
        self.assertEqual(llm.intent("which batteries are low?"), "battery")

    def test_language_and_command(self) -> None:
        self.assertEqual(llm.lang_of("Увімкни розетку"), "uk")
        self.assertEqual(llm.intent("включи розетку"), "command")
        msgs = [
            {"role": "user", "content": "включи розетку"},
            {"role": "assistant"},
            {"role": "tool", "content": json.dumps({"devices": [{"id": "p", "name": "Розетка", "state": {}}]})},
        ]
        self.assertEqual(llm.plan(msgs), ("tool", ("device_command", {"device_id": "p", "values": {"on": True}})))
