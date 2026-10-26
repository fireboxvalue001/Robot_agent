import copy
import json
import unittest
from graphlib import TopologicalSorter
from pathlib import Path

from jsonschema import Draft202012Validator

from backend.planner.knowledge import KnowledgeStore
from backend.server import get_robot_action_templates


ROOT = Path(__file__).resolve().parent.parent


class RobotActionCapabilitiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = json.loads((ROOT / "data/meta-operations.json").read_text(encoding="utf-8"))
        cls.schema = json.loads((ROOT / "schemas/meta-operation-library.schema.json").read_text(encoding="utf-8"))
        cls.by_id = {item["id"]: item for item in cls.library["meta_operations"]}
        cls.actions = [item for item in cls.by_id.values() if item.get("extensions", {}).get("operation_granularity") == "single_action" and not item.get("extensions", {}).get("scenario")]

    def valid_input(self, name, values):
        return Draft202012Validator(self.by_id[f"robot.meta.{name}"]["inputs"]).is_valid(values)

    def test_new_actions_are_single_steps_with_declared_control_profiles(self):
        Draft202012Validator(self.schema).validate(self.library)
        self.assertEqual(len(self.actions), 22)
        for item in self.actions:
            with self.subTest(operation=item["id"]):
                self.assertEqual(item["category"], "robot")
                self.assertEqual(item["status"], "draft")
                self.assertEqual(len(item["operation_tree"]["children"]), 1)
                self.assertIn("control_profile_id", item["inputs"]["required"])
                self.assertTrue(item["extensions"]["control_requirements"])
                self.assertTrue(item["extensions"]["control_profile"]["required_fields"])
                for value in item["operation_tree"]["children"][0]["parameter_bindings"].values():
                    self.assertIn(value.removeprefix("inputs."), item["inputs"]["properties"])

    def test_schema_rejects_macro_disguised_as_single_action(self):
        altered = copy.deepcopy(self.library)
        entry = next(item for item in altered["meta_operations"] if item["id"] == "robot.meta.precision_pinch")
        entry["operation_tree"]["children"].append(copy.deepcopy(entry["operation_tree"]["children"][0]))
        self.assertFalse(Draft202012Validator(self.schema).is_valid(altered))

    def test_composition_examples_only_reference_registered_single_actions(self):
        result = get_robot_action_templates()
        self.assertEqual(result["libraryVersion"], self.library["schema_version"])
        self.assertEqual(len(result["recipes"]), 12)
        self.assertTrue(result["checksum"].startswith("sha256:"))
        for recipe in result["recipes"]:
            self.assertNotIn(recipe["id"], self.by_id)
            for variant in recipe["variants"]:
                self.assertTrue(variant["operation_ids"])
                for operation_id in variant["operation_ids"]:
                    self.assertEqual(len(self.by_id[operation_id]["operation_tree"]["children"]), 1)
        recipes = {item["id"]: item for item in result["recipes"]}
        self.assertEqual(recipes["robot.recipe.preload_then_tighten"]["variants"][0]["operation_ids"],
                         ["robot.meta.preload_seal", "robot.meta.tighten_cap"])
        self.assertEqual(len(recipes["robot.recipe.cap_rotation"]["variants"]), 2)
        self.assertEqual(len(recipes["robot.recipe.insert_or_remove"]["variants"]), 2)

    def test_unpublished_macro_entries_are_removed_but_legacy_ids_remain(self):
        for name in ["upright_and_place_container", "screw_cap", "preload_and_seal_cap", "insert_remove_tip_or_stopper",
                     "tool_assisted_sample_handling", "sort_samples", "dispose_waste_sample", "return_container_upright"]:
            self.assertNotIn(f"robot.meta.{name}", self.by_id)
        for name in ["transfer_object", "transfer_liquid", "mix_sample"]:
            self.assertIn(f"robot.meta.{name}", self.by_id)
        self.assertEqual(self.by_id["robot.meta.transfer_object"]["version"], "1.1.0")

    def test_waste_release_requires_external_authorization(self):
        base = {"object_id": "sample_1", "target_location_id": "waste_zone_1", "control_profile_id": "profile_1", "purpose": "place"}
        self.assertTrue(self.valid_input("release_object", base))
        base["purpose"] = "waste_deposit"
        self.assertFalse(self.valid_input("release_object", base))
        base.update(waste_class_id="registered_waste_class", disposal_confirmed=False)
        self.assertFalse(self.valid_input("release_object", base))
        base["disposal_confirmed"] = True
        self.assertTrue(self.valid_input("release_object", base))

    def test_liquid_quantity_constraints_and_pouring_feedback(self):
        for name, object_key in [("aspirate_liquid", "source_object_id"), ("dispense_liquid", "target_object_id")]:
            base = {"tool_id": "pipette_1", object_key: "bottle_1", "control_profile_id": "profile_1", "volume_ml": 10}
            self.assertTrue(self.valid_input(name, base))
            base["volume_ml"] = 0
            self.assertFalse(self.valid_input(name, base))
        pour = {"source_object_id": "bottle_1", "target_object_id": "bottle_2", "control_profile_id": "profile_1", "target_volume_ml": 10}
        self.assertFalse(self.valid_input("pour_liquid", pour))
        pour["volume_feedback_id"] = "volume_sensor_1"
        self.assertTrue(self.valid_input("pour_liquid", pour))

    def test_action_dependencies_and_no_automatic_retries(self):
        for action in self.actions:
            self.assertEqual(action["failure_policy"]["max_retries"], 0)
            nodes = action["operation_tree"]["children"]
            graph = {node["instance_id"]: set(node.get("depends_on", [])) for node in nodes}
            self.assertEqual(len(tuple(TopologicalSorter(graph).static_order())), 1)

    def test_existing_ai_scopes_are_not_silently_expanded(self):
        for scenario_id, expected_count in [("vd10_single_sample_demo", 5), ("liquid_transfer_demo", 1)]:
            store = KnowledgeStore(scenario_id=scenario_id)
            self.assertEqual(len(store.scenario["operations"]), expected_count)
            self.assertEqual(store.metadata()["source_operation_count"], 93)


if __name__ == "__main__":
    unittest.main()
