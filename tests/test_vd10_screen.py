import copy
import json
import unittest

from backend.planner.conditional import plan_conditional, validate_workflow, validate_scenario
from backend.planner.scenarios import ROOT, resolve, load_config
from backend.planner.types import PlannerRequest
from backend.server import get_vd10_screen_profile


class EmptyAI:
    def generate(self, *args, **kwargs):
        return '{"parameters":{},"unresolved_requests":[]}', {"runtime": "test", "used": True}


class Vd10ScreenTests(unittest.TestCase):
    def setUp(self):
        self.library = json.loads((ROOT / "data/meta-operations.json").read_text(encoding="utf-8"))
        self.operations = {op["id"]: op for op in self.library["meta_operations"]}

    def plan(self, task="query", extra="", mode="deterministic", text=None, knowledge="demo"):
        texts = {"query": "VD10屏幕查询结果；样品编号：S-001", "prepare": "VD10屏幕填写信息；样品编号：S-001；操作员：张三",
            "quality": "VD10屏幕质量状态查看", "robot_quality": "VD10机械臂触屏查看质量状态"}
        return plan_conditional(PlannerRequest(scenario_id="vd10_screen_"+task, model_mode=mode,
            knowledge_mode=knowledge, text=(text or texts[task])+extra), EmptyAI())

    def test_all_action_nodes_are_exact_existing_c2_entries_with_provenance(self):
        original = {"vd10.meta.prepare_test", "vd10.meta.query_test_results", "vd10.meta.inspect_quality_status",
                    "robot.meta.operate_touchscreen", "robot.meta.read_result_from_screen"}
        self.assertFalse(any(id_.startswith("robot.meta.vd10_screen_") for id_ in self.operations))
        for task in ("prepare", "query", "quality", "robot_quality"):
            result = self.plan(task)
            self.assertEqual(result["status"], "logical_pass", result["issues"])
            self.assertFalse(result["execution_allowed"])
            actions = [n for n in result["workflow_definition"]["nodes"] if n["kind"] == "action"]
            self.assertEqual(len(result["reasoning_trace"]["mappings"]), len(actions))
            for node in actions:
                self.assertIn(node["operation_id"], original)
                op = self.operations[node["operation_id"]]
                self.assertEqual(node["operation_name"], op["name"])
                self.assertEqual(node["capability_ref"]["operation_version"], op["version"])
                self.assertEqual(node["capability_ref"]["library_version"], self.library["schema_version"])
                self.assertEqual(node["capability_ref"]["category"], op["category"])

    def test_touchscreen_reuses_legacy_tree_instead_of_inventing_robot_motion(self):
        result = self.plan("robot_quality")
        actions = [n for n in result["workflow_definition"]["nodes"] if n["kind"] == "action"]
        self.assertEqual([n["operation_id"] for n in actions], ["robot.meta.operate_touchscreen"] * 2 + ["robot.meta.read_result_from_screen"])
        self.assertEqual([n["node_ref"] for n in self.operations["robot.meta.operate_touchscreen"]["operation_tree"]["children"]],
                         ["robot.touchscreen.locate_control", "robot.touchscreen.tap", "robot.touchscreen.verify"])
        self.assertEqual(actions[0]["arguments"]["target_control"]["value"], "vd10.menu.enter_quality")
        self.assertEqual(actions[1]["arguments"]["target_control"]["value"], "vd10.quality.open_status")
        self.assertEqual(actions[0]["display"]["title"], "进入质量菜单")
        self.assertEqual(actions[1]["display"]["title"], "打开质量状态")
        self.assertEqual(actions[0]["operation_name"], actions[1]["operation_name"])

    def test_display_templates_must_reference_declared_inputs(self):
        scene = load_config("vd10_screen_robot_quality")
        validate_scenario(scene)
        first = next(n for n in scene["nodes"] if n.get("operation_id"))
        first["display"]["title"] = "操作{{target_control}}"
        validate_scenario(scene)
        first["display"]["title"] = "操作{{invented_input}}"
        with self.assertRaises(ValueError):
            validate_scenario(scene)

    def test_routing_and_missing_inputs(self):
        for text, task in [("VD10屏幕查询结果", "query"), ("VD10屏幕填写信息", "prepare"), ("VD10界面质量检查", "quality"), ("VD10机械臂触屏查看质量状态", "robot_quality")]:
            self.assertEqual(resolve(text)["scenario_id"], "vd10_screen_"+task)
        self.assertEqual(resolve("使用VD10检测样品")["scenario_id"], "vd10_single_sample_demo")
        self.assertEqual(resolve("VD10屏幕填写并查询结果")["reason"], "ambiguous")
        self.assertEqual(self.plan(text="VD10屏幕查询结果")["status"], "needs_input")
        self.assertEqual(self.plan(knowledge="approved_only")["status"], "needs_review")

    def test_dangerous_requests_rejected_without_relying_on_model(self):
        for mode in ("deepseek", "deterministic"):
            self.assertEqual(self.plan(extra="；启动检测", mode=mode)["status"], "unsupported")

    def test_ai_receives_empty_parameter_policy_and_existing_c2_bindings(self):
        class InspectAI:
            def generate(inner_self, messages, **kwargs):
                context = json.loads(messages[-1]["content"])
                self.assertEqual(context["parameters"], {})
                self.assertIn("不需要从用户提取参数", messages[0]["content"])
                self.assertEqual(context["steps"][0]["operation_id"], "robot.meta.operate_touchscreen")
                self.assertEqual(context["steps"][0]["input_bindings"]["target_control"]["value"], "vd10.menu.enter_quality")
                return '{"parameters":{},"unresolved_requests":[]}', {"used": True, "runtime": "test"}
        result = plan_conditional(PlannerRequest(scenario_id="vd10_screen_robot_quality", model_mode="deepseek",
            knowledge_mode="demo", text="VD10机械臂触屏查看质量状态"), InspectAI())
        self.assertEqual(result["status"], "logical_pass")
        self.assertEqual(result["workflow_definition"]["clarifications"], [])

    def test_unknown_missing_disabled_or_wrong_version_action_is_blocked(self):
        workflow = self.plan()["workflow_definition"]
        self.assertEqual(validate_workflow(workflow, self.operations), [])
        for change in ("missing", "unknown", "version", "disabled"):
            altered = copy.deepcopy(workflow)
            operations = copy.deepcopy(self.operations)
            action = next(n for n in altered["nodes"] if n["kind"] == "action")
            if change == "missing":
                action.pop("operation_id")
            elif change == "unknown":
                action["operation_id"] = "robot.meta.invented"
            elif change == "version":
                action["operation_version"] = "99.0.0"
            else:
                operations[action["operation_id"]]["status"] = "disabled"
            self.assertTrue(validate_workflow(altered, operations), change)

    def test_readonly_profile_is_reference_only(self):
        result = get_vd10_screen_profile()
        self.assertFalse(result["execution_allowed"])
        self.assertFalse(result["adapter_implemented"])
        self.assertTrue(set(result["profile"]["capability_ids"]).issubset(self.operations))
        self.assertTrue(all(t["locator"] is None for t in result["profile"]["targets"]))


if __name__ == "__main__":
    unittest.main()
