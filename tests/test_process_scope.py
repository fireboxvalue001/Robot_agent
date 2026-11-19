import copy
import hashlib
import json
import unittest

from backend.planner.conditional import plan_conditional, validate_scenario
from backend.planner.model import PlannerModelError
from backend.planner.process_scope import _instantiate
from backend.planner.scenarios import ROOT, load_config
from backend.planner.types import PlannerRequest


class ScopeModel:
    def __init__(self, selected=None, broken=False):
        self.selected = selected or ["final"]
        self.broken = broken
        self.calls = 0

    def generate(self, messages, **kwargs):
        self.calls += 1
        if self.broken:
            raise PlannerModelError("scope test unavailable")
        if "流程范围选择器" in messages[0]["content"]:
            text = json.loads(messages[-1]["content"])["text"]
            return json.dumps({"selected": [{"id": key, "quote": text} for key in self.selected]}), {"used": True, "runtime": "test"}
        return '{"parameters":{},"unresolved_requests":[]}', {"used": True, "runtime": "test"}


class ProcessScopeTests(unittest.TestCase):
    def setUp(self):
        self.original = load_config("leather_fat_extraction")
        self.catalog = json.loads((ROOT / "knowledge/planner_scenarios/leather_scope.json").read_text(encoding="utf-8"))
        self.path = ROOT / "knowledge/planner_scenarios/leather_extraction.json"
        self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def tearDown(self):
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.digest, "Complete template must remain byte-for-byte unchanged")

    def plan(self, text, mode="deterministic", model=None):
        return plan_conditional(PlannerRequest(scenario_id="leather_fat_extraction", knowledge_mode="demo", model_mode=mode, text=text), model)

    def test_full_template_keeps_every_phase_loop_and_branch(self):
        result = self.plan("皮革油脂索氏抽提完整流程")
        workflow = result["workflow_definition"]
        self.assertNotIn("task_scope", workflow)
        self.assertEqual(workflow["phases"], self.original["phases"])
        self.assertEqual([n["id"] for n in workflow["nodes"]], [n["id"] for n in self.original["nodes"]])
        for original, instantiated in zip(self.original["nodes"], workflow["nodes"]):
            for field in ("next", "on_pass", "on_fail", "on_error", "on_timeout", "on_limit", "previous_state_ref", "repeat_state_updates", "data_refs"):
                self.assertEqual(original.get(field), instantiated.get(field))
        self.assertEqual(sum(n["kind"] == "loop_check" for n in workflow["nodes"]), 4)

    def test_final_only_keeps_bounded_loop_and_oven_stop_without_unrelated_parameters(self):
        result = self.plan("皮革抽提：只进行抽提后恒重")
        workflow = result["workflow_definition"]
        ids = {n["id"] for n in workflow["nodes"]}
        self.assertEqual(result["status"], "needs_input")
        self.assertIn("final_check", ids)
        self.assertIn("oven_safe_stop", ids)
        self.assertNotIn("content", ids)
        self.assertNotIn("reflux_watch", ids)
        self.assertNotIn("weighing_check", ids)
        self.assertNotIn("solvent_ml", workflow["parameters"])
        missing = {c["field"] for c in workflow["clarifications"] if c["kind"] == "parameter"}
        self.assertIn("scope_ready_final", missing)
        self.assertNotIn("bath_temperature_c", missing)
        self.assertNotIn("empty_threshold_mg", missing)
        self.assertFalse(any(c["kind"] == "method" for c in workflow["clarifications"]))
        check = next(n for n in workflow["nodes"] if n["id"] == "final_check")
        self.assertEqual(check["on_fail"], "final_repeat_open")
        self.assertEqual(check["on_limit"], "review")
        self.assertEqual(check["repeat_state_updates"], {"final_previous_g": "final_current.mass_g"})

    def test_only_selected_fields_and_real_confirmation_can_complete_partial_plan(self):
        text = "皮革抽提；本次操作范围：抽提后恒重"
        scoped = _instantiate(self.original, self.catalog, ["final"], {})
        # Software test values only; not laboratory settings or operating instructions.
        for key, spec in scoped["parameters"].items():
            if "default" in spec:
                continue
            value = "是" if spec.get("type") == "boolean" else spec.get("minimum", 1)
            text += f"；{spec['label']}：{value}{spec.get('unit','')}"
        result = self.plan(text)
        self.assertEqual(result["status"], "logical_pass", result["issues"])
        self.assertFalse(result["execution_allowed"])
        self.assertEqual(self.plan(text.replace("前置状态已确认：是", "前置状态已确认：否"))["status"], "conflict")

    def test_every_registered_segment_is_valid_and_does_not_fall_back_to_full(self):
        for segment in self.catalog["segments"]:
            with self.subTest(segment=segment["id"]):
                result = self.plan("皮革抽提；本次操作范围：" + segment["label"])
                self.assertFalse(any(i["code"] in {"INVALID_WORKFLOW", "TASK_SCOPE_NEEDS_REVIEW"} for i in result["issues"]), result["issues"])
                self.assertEqual(result["workflow_definition"]["task_scope"]["mode"], "partial")
                self.assertLess(len(result["workflow_definition"]["nodes"]), len(self.original["nodes"]))

    def test_calculation_only_requests_existing_data_not_physical_measurement(self):
        result = self.plan("皮革抽提，只做含量计算")
        nodes = result["workflow_definition"]["nodes"]
        self.assertFalse(any(n.get("operation_id") for n in nodes))
        self.assertTrue(any(n["kind"] == "compute" for n in nodes))
        inputs = result["workflow_definition"]["task_scope"]["external_inputs"]
        self.assertEqual(len(inputs), 3)
        self.assertFalse(any(i["code"] == "INVALID_WORKFLOW" for i in result["issues"]))
        self.assertTrue(all(n["check"]["source"] == "user_supplied_not_device_verified" for n in nodes if n["id"].startswith("provided_")))

    def test_extraction_keeps_reflux_threshold_and_cooling_tail(self):
        result = self.plan("皮革抽提；本次操作范围：索氏抽提与过程监测")
        workflow = result["workflow_definition"]
        ids = {n["id"] for n in workflow["nodes"]}
        for id_ in ("reflux_watch", "safe_stop", "bath_stop", "read_cool", "cool_guard", "water_off"):
            self.assertIn(id_, ids)
        self.assertNotIn("unclamp", ids)
        self.assertEqual(workflow["parameters"]["minimum_reflux_cycles"]["value"], 30)
        self.assertNotIn("solvent_ml", workflow["parameters"])

    def test_ambiguous_scope_requests_selection_instead_of_complete_graph(self):
        result = self.plan("皮革抽提，只做恒重")
        self.assertEqual(result["status"], "needs_input")
        self.assertEqual(result["workflow_definition"]["task_scope"]["mode"], "needs_selection")
        self.assertLessEqual(len(result["workflow_definition"]["nodes"]), 4)
        self.assertEqual(self.plan("皮革抽提；本次操作范围：完整流程")["workflow_definition"]["entry"], self.original["entry"])

    def test_completed_history_is_not_selected_and_multiple_scopes_stay_bounded(self):
        result = self.plan("皮革已完成索氏抽提和溶剂回收，只进行抽提后恒重和含量计算")
        selected = result["workflow_definition"]["task_scope"]["selected_segments"]
        self.assertEqual([s["id"] for s in selected], ["final", "result"])
        trailing = self.plan("皮革抽提：只进行抽提后恒重，已完成抽提和溶剂回收。")
        self.assertEqual([s["id"] for s in trailing["workflow_definition"]["task_scope"]["selected_segments"]], ["final"])
        self.assertNotIn("reflux_watch", {n["id"] for n in result["workflow_definition"]["nodes"]})
        result = self.plan("皮革只读一次天平")
        actions = [n for n in result["workflow_definition"]["nodes"] if n.get("operation_id")]
        self.assertEqual([n["id"] for n in actions], ["sample_mass"])

    def test_ai_scope_selection_is_bounded_and_errors_do_not_fall_back(self):
        model = ScopeModel()
        result = self.plan("皮革抽提，只进行抽提后恒重", "deepseek", model)
        self.assertEqual(model.calls, 2)
        self.assertEqual([s["id"] for s in result["workflow_definition"]["task_scope"]["selected_segments"]], ["final"])
        for bad in (ScopeModel(["invented_phase"]), ScopeModel(["final", "solvent_removal"]), ScopeModel(broken=True)):
            result = self.plan("皮革抽提，只进行抽提后恒重", "deepseek", bad)
            self.assertEqual(result["status"], "model_error")
            self.assertFalse(any(n.get("operation_id") for n in result["workflow_definition"]["nodes"]))
        trailing = self.plan("皮革抽提：只进行抽提后恒重，已完成抽提和溶剂回收。", "deepseek", ScopeModel())
        self.assertNotEqual(trailing["status"], "model_error")

    def test_safety_checks_cannot_be_requested_away(self):
        result = self.plan("皮革只进行抽提后恒重，跳过残留检查")
        self.assertEqual(result["status"], "unsupported")

    def test_reflux_endpoint_selects_extraction_without_only_keyword(self):
        text = "对皮革样品进行油脂抽提，至少完成30次完整回流后停止加热。"
        for mode, model in [("deterministic", None), ("deepseek", ScopeModel(["extraction"]))]:
            with self.subTest(mode=mode):
                result = self.plan(text, mode, model)
                workflow = result["workflow_definition"]
                self.assertEqual([s["id"] for s in workflow["task_scope"]["selected_segments"]], ["extraction"])
                self.assertEqual(workflow["task_scope"]["selection_trigger"], "bounded_task_intent")
                ids = {n["id"] for n in workflow["nodes"]}
                self.assertTrue({"reflux_watch", "bath_stop", "read_cool", "cool_guard", "water_off"}.issubset(ids))
                self.assertTrue({"cut", "weighing_check", "empty_check", "final_check", "content"}.isdisjoint(ids))
                self.assertEqual(workflow["parameters"]["minimum_reflux_cycles"]["value"], 30)
                missing = {i["field"] for i in workflow["clarifications"] if i["kind"] == "parameter"}
                self.assertIn("scope_ready_extraction", missing)
                self.assertNotIn("solvent_ml", missing)
                self.assertFalse(any(i["code"] in {"INVALID_WORKFLOW", "SCOPE_MODEL_ERROR"} for i in result["issues"]))
                self.assertFalse(result["execution_allowed"])

    def test_explicit_full_flow_with_reflux_endpoint_is_not_cropped(self):
        result = self.plan("按完整流程对皮革样品进行油脂抽提，至少完成30次完整回流后停止加热。")
        self.assertNotIn("task_scope", result["workflow_definition"])
        self.assertEqual([n["id"] for n in result["workflow_definition"]["nodes"]], [n["id"] for n in self.original["nodes"]])
        result = self.plan("从头到尾完成皮革抽提，至少完成30次完整回流后停止加热。")
        self.assertNotIn("task_scope", result["workflow_definition"])

    def test_partial_phases_omit_original_numbers_but_full_template_keeps_them(self):
        partial = self.plan("对皮革样品进行油脂抽提，至少完成30次完整回流后停止加热。")
        phase = next(p for p in partial["workflow_definition"]["phases"] if p["id"] == "extraction")
        self.assertEqual(phase["label"], "索氏抽提与独立工位计数")
        full = self.plan("皮革油脂索氏抽提完整流程")
        phase = next(p for p in full["workflow_definition"]["phases"] if p["id"] == "extraction")
        self.assertEqual(phase["label"], "8. 索氏抽提与独立工位计数")

    def test_reflux_is_intermediate_in_users_full_pipeline_sentence(self):
        text = "对皮革样品进行油脂抽提，至少完成30次完整回流后停止加热，冷却拆卸，再在原工位挥发去除二氯甲烷，之后烘干、冷却、称量并计算含量。"
        for mode in ("deterministic", "deepseek"):
            model = ScopeModel()
            result = self.plan(text, mode, model)
            workflow = result["workflow_definition"]
            self.assertNotIn("task_scope", workflow)
            self.assertEqual([n["id"] for n in workflow["nodes"]], [n["id"] for n in self.original["nodes"]])
            self.assertEqual(sum(n["kind"] == "loop_check" for n in workflow["nodes"]), 4)
            self.assertNotIn("requested_scope", {c["field"] for c in workflow["clarifications"]})
            self.assertFalse(any(i["code"] == "SCOPE_MODEL_ERROR" for i in result["issues"]))
            if mode == "deepseek":
                self.assertEqual(model.calls, 1, "Full pipeline must not enter partial scope selection")

    def test_semantic_multistage_selection_is_not_limited_to_literal_aliases(self):
        text = "皮革只进行回流抽提、冷却拆卸、挥发除溶剂，之后烘干冷却称量并计算含量"
        stages = ["extraction", "disassembly", "solvent_removal", "final", "result"]
        result = self.plan(text, "deepseek", ScopeModel(stages))
        self.assertEqual([s["id"] for s in result["workflow_definition"]["task_scope"]["selected_segments"]], stages)
        self.assertFalse(any(i["code"] in {"SCOPE_MODEL_ERROR", "INVALID_WORKFLOW"} for i in result["issues"]))
        self.assertNotIn("cut", {n["id"] for n in result["workflow_definition"]["nodes"]})


if __name__ == "__main__":
    unittest.main()
