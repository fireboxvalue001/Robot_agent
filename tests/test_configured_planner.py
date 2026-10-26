import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from backend.planner.conditional import plan_conditional, validate_scenario, validate_workflow
from backend.planner.process_parameters import parameter_value
from backend.planner.scenarios import ROOT, catalog, load_config, local_json, resolve
from backend.planner.service import PlannerService
from backend.planner.types import PlannerRequest
from backend.planner.router import get_scenario_catalog, resolve_scenario, ScenarioSelection


class UnusedModel:
    def generate(self, *args, **kwargs):
        raise AssertionError("Offline tests must not invoke a model")


class ConfiguredPlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for folder in ["data", "schemas", "knowledge/planner_scenarios"]:
            shutil.copytree(ROOT / folder, self.root / folder)

    def tearDown(self):
        self.temp.cleanup()

    def request(self, text="样品定时静置", scenario="sample_hold_config"):
        return PlannerRequest(scenario_id=scenario, knowledge_mode="demo", model_mode="deterministic", text=text)

    def complete_text(self):
        return "样品定时静置；样品标识：S-01；静置位置：暂存点A；静置时长：30秒；存放方式：遮光；样品标识已核对：是"

    def test_second_scene_uses_same_engine_with_no_extraction_parameters(self):
        draft = plan_conditional(self.request(), UnusedModel(), self.root)
        self.assertEqual(draft["status"], "needs_input")
        self.assertEqual({row["type"] for row in draft["workflow_definition"]["clarifications"]}, {"number", "string", "boolean"})
        result = plan_conditional(self.request(self.complete_text()), UnusedModel(), self.root)
        self.assertEqual(result["status"], "logical_pass", result["issues"])
        self.assertEqual(result["workflow_definition"]["name"], "样品定时静置")
        self.assertIsNone(result["workflow_definition"]["method"])
        self.assertFalse(result["execution_allowed"])
        self.assertNotIn("minimum_reflux_cycles", result["workflow_definition"]["parameters"])

    def test_boolean_false_unknown_enum_and_wrong_units_do_not_pass(self):
        for old, new in [("已核对：是", "已核对：否"), ("存放方式：遮光", "存放方式：加热"), ("30秒", "30min")]:
            result = plan_conditional(self.request(self.complete_text().replace(old, new)), UnusedModel(), self.root)
            self.assertNotEqual(result["status"], "logical_pass")

    def test_new_scene_is_discovered_from_json_without_python_dispatch_changes(self):
        scene = load_config("sample_hold_config", self.root)
        scene.update(scenario_id="custom_process", name="自定义流程", knowledge_id="autolab.test.custom")
        (self.root / "knowledge/planner_scenarios/custom_process.json").write_text(json.dumps(scene), encoding="utf-8")
        path = self.root / "knowledge/planner_scenarios/registry.json"
        registry = json.loads(path.read_text(encoding="utf-8"))
        registry["scenarios"].append({"id":"custom_process", "name":"自定义流程", "engine":"conditional", "file":"knowledge/planner_scenarios/custom_process.json", "routing_patterns":["自定义流程"], "ui":{}})
        path.write_text(json.dumps(registry), encoding="utf-8")
        self.assertEqual(resolve("自定义流程", root=self.root)["scenario_id"], "custom_process")
        result = plan_conditional(self.request(self.complete_text(), "custom_process"), UnusedModel(), self.root)
        self.assertEqual(result["status"], "logical_pass")
        self.assertEqual(result["workflow_definition"]["name"], "自定义流程")

    def test_unknown_and_ambiguous_intents_require_selection(self):
        self.assertEqual(resolve("未知实验", root=self.root)["status"], "needs_input")
        ambiguity = resolve("皮革提取后进行VD10检测", root=self.root)
        self.assertEqual(ambiguity["status"], "needs_input")
        self.assertEqual(len(ambiguity["candidates"]), 2)
        self.assertEqual(resolve("未知实验", "sample_hold_config", self.root)["status"], "resolved")

    def test_disabled_scenes_cannot_be_selected(self):
        path = self.root / "knowledge/planner_scenarios/registry.json"
        registry = json.loads(path.read_text(encoding="utf-8"))
        next(e for e in registry["scenarios"] if e["id"] == "sample_hold_config")["enabled"] = False
        path.write_text(json.dumps(registry), encoding="utf-8")
        self.assertEqual(resolve("样品定时静置", root=self.root)["status"], "needs_input")
        with self.assertRaises(ValueError):
            resolve("任务", "sample_hold_config", self.root)

    def test_rejects_unknown_phase_parameter_and_unsafe_file_paths(self):
        scene = load_config("sample_hold_config", self.root)
        scene["nodes"][0]["phase_id"] = "not_registered"
        with self.assertRaises(ValueError):
            validate_scenario(scene, self.root)
        scene = load_config("sample_hold_config", self.root)
        scene["nodes"][0]["requires"] = ["not_registered"]
        with self.assertRaises(ValueError):
            validate_scenario(scene, self.root)
        with self.assertRaises(ValueError):
            local_json(self.root, "../../private.json", "data")

    def test_generic_workflow_rejects_unbounded_cycles_and_wrong_argument_types(self):
        result = plan_conditional(self.request(self.complete_text()), UnusedModel(), self.root)
        workflow = result["workflow_definition"]
        ops = {op["id"]:op for op in local_json(self.root, "data/meta-operations.json", "data")["meta_operations"]}
        invalid = copy.deepcopy(workflow)
        next(n for n in invalid["nodes"] if n["id"] == "move")["next"] = "pick"
        self.assertTrue(any("循环" in e for e in validate_workflow(invalid, ops, self.root)))
        invalid = copy.deepcopy(workflow)
        next(n for n in invalid["nodes"] if n["id"] == "pick")["arguments"]["object_id"] = {"value":123}
        self.assertTrue(any("不一致" in e for e in validate_workflow(invalid, ops, self.root)))

    def test_catalog_and_auto_service_route(self):
        self.assertGreaterEqual(len(catalog()), 4)
        self.assertTrue(any(e["id"] == "sample_hold_config" for e in get_scenario_catalog()["scenarios"]))
        self.assertEqual(resolve_scenario(ScenarioSelection(text="样品定时静置"))["scenario_id"], "sample_hold_config")
        result = PlannerService().plan(self.request(self.complete_text(), "auto"))
        self.assertEqual(result.scenario_id, "sample_hold_config")
        self.assertEqual(result.status, "logical_pass")

    def test_typed_parameters_reject_coercion(self):
        for value, spec in [(True, {"label":"值", "type":"number"}), ("true", {"label":"确认", "type":"boolean"}), (1, {"label":"文字", "type":"string"})]:
            with self.assertRaises(ValueError):
                parameter_value(value, spec)

    def test_optional_field_used_by_a_node_is_still_required(self):
        path = self.root / "knowledge/planner_scenarios/sample_hold.json"
        scene = json.loads(path.read_text(encoding="utf-8"))
        scene["parameters"]["hold_seconds"]["required"] = False
        path.write_text(json.dumps(scene), encoding="utf-8")
        result = plan_conditional(self.request(), UnusedModel(), self.root)
        self.assertIn("hold_seconds", {c["field"] for c in result["workflow_definition"]["clarifications"]})
        self.assertNotEqual(result["status"], "logical_pass")

    def test_invalid_enum_types_and_missing_default_sources_are_configuration_errors(self):
        scene = load_config("sample_hold_config", self.root)
        scene["parameters"]["label_confirmed"]["enum"] = [1]
        with self.assertRaises(ValueError):
            validate_scenario(scene, self.root)
        scene = load_config("sample_hold_config", self.root)
        scene["parameters"]["hold_seconds"]["default"] = 30
        with self.assertRaises(ValueError):
            validate_scenario(scene, self.root)


if __name__ == "__main__":
    unittest.main()
