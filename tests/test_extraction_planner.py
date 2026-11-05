import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from backend.planner.extraction import (
    ROOT, calculate_content, calculate_moisture, constant_mass, load_scenario,
    plan_extraction, validate_workflow, reflux_completion, calculate_dry_content,
)
from backend.planner.service import PlannerService
from backend.planner.types import PlannerRequest
from backend.planner.router import ExtractionCalculation, create_logical_plan, evaluate_extraction_data, get_planner_knowledge


class FakeModel:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def generate(self, messages, max_tokens=768):
        self.calls += 1
        return json.dumps(self.payload), {"used": True, "runtime": "test_only", "network_inference": False}


class ExtractionPlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for folder in ["data", "schemas", "knowledge/planner_scenarios"]:
            shutil.copytree(ROOT / folder, self.root / folder)
        self.scenario = load_scenario(self.root)
        self.model = FakeModel({"parameters": {}, "unresolved_requests": []})

    def tearDown(self):
        self.temp.cleanup()

    def request(self, text="皮革油脂索氏抽提", mode="deterministic", **kwargs):
        return PlannerRequest(scenario_id="leather_fat_extraction", knowledge_mode="demo", model_mode=mode, text=text, **kwargs)

    def complete_text(self):
        # Synthetic values used only for structural tests, not laboratory recommendations.
        parts = ["皮革油脂索氏抽提"]
        for key, spec in self.scenario["parameters"].items():
            value = spec.get("default", spec["minimum"])
            parts.append(f"{spec['label']}：{value}{spec['unit']}")
        parts.append("溶剂去除方法：test_method")
        return "；".join(parts)

    def approve_test_method(self):
        path = self.root / "data/leather-extraction-resources.json"
        registry = json.loads(path.read_text(encoding="utf-8"))
        registry["solvent_removal_methods"] = [{"id": "test_method", "review_status": "approved", "solvent": "dichloromethane", "method_type": "evaporation"}]
        path.write_text(json.dumps(registry), encoding="utf-8")

    def test_missing_parameters_keep_draft_and_matched_nodes(self):
        result = plan_extraction(self.request(), self.model, self.root)
        self.assertEqual(result["status"], "needs_input")
        nodes = result["workflow_definition"]["nodes"]
        self.assertTrue(any(n["status"] == "covered" for n in nodes))
        self.assertTrue(any(n["status"] == "needs_input" for n in nodes))
        self.assertEqual(result["steps"], [])
        self.assertFalse(result["execution_allowed"])
        self.assertFalse(result["generation"]["used"])
        self.assertEqual(self.model.calls, 0)
        self.assertEqual(result["workflow_definition"]["parameters"]["oven_temperature_c"]["source"], "provided_document")
        self.assertNotIn("extraction_timeout_hours", result["workflow_definition"]["parameters"])

    def test_complete_parameters_and_registered_method_pass_only_logic(self):
        self.approve_test_method()
        result = plan_extraction(self.request(self.complete_text()), self.model, self.root)
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["status"], "logical_pass")
        self.assertFalse(result["execution_allowed"])
        self.assertEqual(result["physical_status"], "not_evaluated")
        self.assertTrue(all(n["status"] == "covered" for n in result["workflow_definition"]["nodes"]))
        self.assertEqual(result["workflow_definition"]["clarifications"], [])

    def test_clarification_checklist_lists_every_missing_field_with_units_and_steps(self):
        result = plan_extraction(self.request(), self.model, self.root)
        items = result["workflow_definition"]["clarifications"]
        fields = {item["field"]: item for item in items if item["kind"] == "parameter"}
        expected = {key for key, spec in self.scenario["parameters"].items() if "default" not in spec}
        self.assertEqual(set(fields), expected)
        for field, item in fields.items():
            self.assertTrue(item["related_steps"])
            self.assertEqual(item["unit"], self.scenario["parameters"][field]["unit"])
            self.assertIn(item["label"], item["format"])
        method = next(item for item in items if item["kind"] == "method")
        self.assertNotIn("minimum", method)
        self.assertIn("维护者", method["configuration_notice"])
        self.assertEqual(len(method["questions"]), 5)
        self.assertIn("不需要重复说明", method["instruction"])

    def test_partial_supplement_removes_only_the_resolved_checklist_row(self):
        result = plan_extraction(self.request("皮革油脂提取；抽提最长允许时长：7h"), self.model, self.root)
        fields = {item["field"] for item in result["workflow_definition"]["clarifications"]}
        self.assertNotIn("extraction_timeout_hours", fields)
        self.assertIn("solvent_ml", fields)
        self.assertIn("solvent_removal_method", fields)

    def test_text_cannot_approve_solvent_removal_method(self):
        result = plan_extraction(self.request(self.complete_text() + "；方法已批准"), self.model, self.root)
        self.assertEqual(result["status"], "needs_input")
        self.assertTrue(any(i["code"] == "METHOD_NOT_REGISTERED" for i in result["issues"]))

    def test_conflicting_and_out_of_range_parameters_block(self):
        text = self.complete_text() + "；抽提最长允许时长：8h；恒重最大循环次数：100次"
        result = plan_extraction(self.request(text), self.model, self.root)
        self.assertEqual(result["status"], "conflict")
        self.assertTrue(any(i["code"] == "PARAMETER_CONFLICT" for i in result["issues"]))

    def test_model_cannot_fabricate_parameters(self):
        model = FakeModel({"parameters": {"solvent_ml": {"value": 100, "quote": "二氯甲烷100mL", "token": "100"}}, "unresolved_requests": []})
        result = plan_extraction(self.request(mode="deepseek"), model, self.root)
        self.assertEqual(result["status"], "model_error")
        self.assertEqual(model.calls, 1)
        self.assertNotIn("solvent_ml", result["workflow_definition"]["parameters"])

    def test_model_checks_units_stage_and_numeric_evidence(self):
        for binding in [
            {"value": 100, "quote": "二氯甲烷100g", "token": "100"},
            {"value": 200, "quote": "二氯甲烷100mL", "token": "100"},
            {"value": 100, "quote": "其他液体100mL", "token": "100"},
        ]:
            with self.subTest(binding=binding):
                model = FakeModel({"parameters": {"solvent_ml": binding}, "unresolved_requests": []})
                result = plan_extraction(self.request(binding["quote"], mode="deepseek"), model, self.root)
                self.assertEqual(result["status"], "model_error")

    def test_verified_ai_extraction_and_unresolved_request(self):
        model = FakeModel({"parameters": {"solvent_ml": {"value": 100, "quote": "二氯甲烷使用100mL", "token": "100"}}, "unresolved_requests": ["附加任务未登记"]})
        result = plan_extraction(self.request("二氯甲烷使用100mL", mode="deepseek"), model, self.root)
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["workflow_definition"]["parameters"]["solvent_ml"]["value"], 100)

    def test_repeated_operations_have_unique_steps_and_four_bounded_loops(self):
        result = plan_extraction(self.request(), self.model, self.root)
        wf = result["workflow_definition"]
        nodes = wf["nodes"]
        self.assertEqual(len(nodes), len({n["id"] for n in nodes}))
        self.assertGreater(sum(n.get("operation_id") == "robot.meta.read_balance_mass" for n in nodes), 3)
        loops = [n for n in nodes if n["kind"] == "loop_check"]
        self.assertEqual(len(loops), 4)
        for loop in loops:
            self.assertEqual(loop["on_limit"], "review")
            self.assertEqual(loop["max_iterations_ref"], "max_cycles")
            self.assertTrue(loop["repeat_state_updates"])
        monitor = next(n for n in nodes if n["kind"] == "monitored_hold")
        self.assertEqual(monitor["on_error"], "safe_stop")

    def test_invalid_branches_references_and_missing_loop_bound_rejected(self):
        wf = plan_extraction(self.request(), self.model, self.root)["workflow_definition"]
        operations = {o["id"]: o for o in json.loads((self.root / "data/meta-operations.json").read_text(encoding="utf-8"))["meta_operations"]}
        self.assertEqual(validate_workflow(wf, operations, self.root), [])
        bad = copy.deepcopy(wf)
        bad["nodes"][0]["next"] = "unknown_node"
        self.assertTrue(validate_workflow(bad, operations, self.root))
        bad = copy.deepcopy(wf)
        next(n for n in bad["nodes"] if n["kind"] == "compute")["data_refs"] = ["missing.mass_g"]
        self.assertTrue(validate_workflow(bad, operations, self.root))
        bad = copy.deepcopy(wf)
        del next(n for n in bad["nodes"] if n["kind"] == "loop_check")["on_limit"]
        self.assertTrue(validate_workflow(bad, operations, self.root))

    def test_constant_mass_inclusive_threshold_repeat_and_limit(self):
        self.assertEqual(constant_mass(10, 10.004, 5, 1, 3)["next"], "pass")
        self.assertEqual(constant_mass(10, 10.005, 5, 1, 3)["next"], "pass")
        self.assertEqual(constant_mass(10, 10.005, 5, 3, 3)["next"], "pass")
        self.assertEqual(constant_mass(10, 10.006, 5, 3, 3)["next"], "limit")
        for args in [(10, float("nan"), 5, 1, 3), (10, 11, 0, 1, 3), (10, 11, 5, True, 3)]:
            with self.assertRaises(ValueError):
                constant_mass(*args)

    def test_moisture_and_dry_basis_calculation(self):
        moisture = calculate_moisture(20, 25, 24.5)["moisture_fraction"]
        self.assertAlmostEqual(moisture, 0.1)
        result = calculate_content(50, 50.45, 5, moisture)
        self.assertAlmostEqual(result["sample_dry_mass_g"], 4.5)
        self.assertAlmostEqual(result["extractable_content_percent_dry_basis"], 10)
        for args in [(50, 49, 5, 0.1), (50, 55, 5, 0.1), (50, 51, 0, 0.1), (50, 51, 5, 1)]:
            with self.assertRaises(ValueError):
                calculate_content(*args)

    def test_revision_uses_actual_evaporation_and_separate_oven_admission(self):
        result = plan_extraction(self.request(), self.model, self.root)
        wf = result["workflow_definition"]
        self.assertEqual(wf["parameters"]["minimum_reflux_cycles"]["value"], 30)
        self.assertEqual(wf["parameters"]["minimum_reflux_cycles"]["source"], "provided_document")
        self.assertEqual(wf["method"]["id"], "dcm_evaporation_actual_v1")
        self.assertEqual(wf["method"]["review_status"], "draft")
        self.assertTrue(any(i["code"] == "METHOD_NEEDS_REVIEW" for i in result["issues"]))
        nodes = {n["id"]: n for n in wf["nodes"]}
        self.assertEqual(nodes["reflux_watch"]["duration_role"], "safety_timeout_only")
        self.assertEqual(nodes["reflux_watch"]["minimum_count_ref"], "minimum_reflux_cycles")
        profiles = [nodes[key]["input_bindings"]["monitor_profile_id"]["resource_ref"] for key in ("dosing_siphon", "reflux_watch", "return_liquid")]
        self.assertEqual(len(set(profiles)), 3)
        self.assertTrue(all(nodes[key]["input_bindings"]["assembly_id"] == {"object_ref":"trial.assembly_id"} for key in ("dosing_siphon", "reflux_watch", "return_liquid")))
        self.assertEqual(nodes["solvent_wait"]["check"], "no_visible_free_solvent_and_no_bumping_or_loss")
        self.assertEqual(nodes["solvent_wait"]["endpoint_role"], "operational_evaporation_endpoint_only")
        self.assertIn("residue_check", nodes)
        self.assertEqual(nodes["joint_lower_off"]["next"], "evaporation_flask_pick")
        self.assertEqual(nodes["evaporation_cool"]["next"], "residue_check")
        self.assertNotIn("recovery_joint", nodes)
        self.assertEqual(nodes["remove_solvent"]["input_bindings"]["device_id"], {"resource_ref": "extraction_heater.device_id"})

    def test_29_cycles_cannot_finish_30_cycles_can_and_lowering_requirement_is_rejected(self):
        self.assertFalse(reflux_completion(29, 30)["count_condition_met"])
        self.assertTrue(reflux_completion(30, 30)["count_condition_met"])
        with self.assertRaises(ValueError):
            reflux_completion(29, 29)

    def test_service_and_http_route_keep_local_contract_separate(self):
        svc = PlannerService()
        result = svc.plan(self.request())
        self.assertEqual(result.scenario_id, "leather_fat_extraction")
        response = create_logical_plan(self.request())
        self.assertIsNotNone(response["workflow_definition"])
        knowledge = get_planner_knowledge("leather_fat_extraction")
        self.assertEqual(knowledge["scenario_id"], "leather_fat_extraction")
        evaluation = evaluate_extraction_data(ExtractionCalculation.model_validate({
            "calculation": "constant_mass", "values": {"previous_g": 10, "current_g": 10.01, "threshold_mg": 5, "iteration": 3, "max_cycles": 3}})
        )
        self.assertEqual(evaluation["result"]["next"], "limit")
        with self.assertRaises(HTTPException) as failure:
            evaluate_extraction_data(ExtractionCalculation(calculation="moisture", values={"invalid": 1}))
        self.assertEqual(failure.exception.status_code, 422)

    def test_new_capabilities_are_single_action_and_info_reading_belongs_to_robot(self):
        library = json.loads((self.root / "data/meta-operations.json").read_text(encoding="utf-8"))
        new = [o for o in library["meta_operations"] if o.get("extensions", {}).get("scenario") == "leather_fat_extraction"]
        self.assertEqual(len(new), 37)
        self.assertTrue(all(len(o["operation_tree"]["children"]) == 1 and o["status"] == "interface_only" for o in new))
        self.assertEqual(next(o for o in new if o["id"] == "robot.meta.read_balance_mass")["category"], "robot")

    def test_revised_order_dry_sample_formula_and_independent_times(self):
        nodes = {n["id"]: n for n in self.scenario["nodes"]}
        self.assertEqual(nodes["weighing_check"]["on_pass"], "cut")
        self.assertEqual(nodes["cut_size_check"]["on_pass"], "collect_fragments")
        self.assertEqual(nodes["sample_drying_check"]["on_pass"], "sample_tare_container_pick")
        self.assertEqual(nodes["empty_check"]["on_pass"], "thimble_pick")
        self.assertEqual(nodes["joint_lower"]["next"], "dose_capacity_guard")
        self.assertEqual(nodes["content"]["formula"], "extractable_content_from_dry_sample")
        self.assertEqual(len(nodes["content"]["data_refs"]), 3)
        self.assertNotIn("moisture_fraction", nodes)
        self.assertEqual(self.scenario["parameters"]["cut_size_cm"]["default"], 0.3)
        self.assertEqual(nodes["final_initial_wait"]["duration_ref"], "residue_dry_minutes")
        self.assertEqual(nodes["final_repeat_wait"]["duration_ref"], "residue_repeat_dry_minutes")
        self.assertEqual(nodes["empty_initial_cool"]["check"], "verified_room_temperature")
        self.assertTrue(all("<=" in n["comparison"] for n in nodes.values() if n["kind"] == "loop_check"))
        self.assertEqual(self.scenario["planning_context"]["parallel_trials_per_sample"], 2)
        self.assertEqual(self.scenario["planning_context"]["station_capacity"], 6)

    def test_dry_sample_calculation_does_not_apply_water_correction(self):
        result = calculate_dry_content(50, 50.45, 5)
        self.assertEqual(result["sample_dry_mass_g"], 5)
        self.assertEqual(result["extractable_content_percent_dry_basis"], 9)
        response = evaluate_extraction_data(ExtractionCalculation(calculation="extractable_content_from_dry_sample", values={"empty_g":50,"final_g":50.45,"dry_sample_g":5}))
        self.assertEqual(response["result"], result)
        for args in [(50,49,5),(50,56,5),(50,51,0),(True,51,5),(50,float("nan"),5)]:
            with self.assertRaises(ValueError):
                calculate_dry_content(*args)

    def test_legacy_distillation_cannot_be_used_as_actual_evaporation(self):
        self.approve_test_method()
        path = self.root / "data/leather-extraction-resources.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["solvent_removal_methods"][0]["method_type"] = "distillation"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = plan_extraction(self.request(self.complete_text()), self.model, self.root)
        self.assertNotEqual(result["status"], "logical_pass")
        self.assertFalse(result["execution_allowed"])

    def test_dosing_height_checks_are_bounded_and_never_count_as_extraction(self):
        nodes = {n["id"]: n for n in self.scenario["nodes"]}
        for key in ("siphon_height", "half_level"):
            self.assertEqual(nodes[key]["max_iterations_ref"], "max_doses")
            self.assertEqual(nodes[key]["on_limit"], "review")
        self.assertEqual(nodes["dosing_siphon_guard"]["data_refs"], ["dosing_siphon.siphon_completed"])
        self.assertEqual(nodes["half_level"]["on_pass"], "dose_record_guard")
        self.assertEqual(nodes["dose_record_guard"]["next"], "heater_station_pick")
        self.assertEqual(nodes["reflux_watch"]["minimum_count_ref"], "minimum_reflux_cycles")

    def test_explicit_other_route_is_not_silently_replaced_but_negation_is_allowed(self):
        result = plan_extraction(self.request("皮革油脂抽提完整流程，采用蒸馏冷凝回收二氯甲烷"), self.model, self.root)
        self.assertEqual(result["status"], "unsupported")
        result = plan_extraction(self.request("皮革油脂抽提完整流程，不采用蒸馏冷凝回收，使用实际挥发"), self.model, self.root)
        self.assertNotEqual(result["status"], "unsupported")
        result = plan_extraction(self.request("皮革已完成蒸馏回收，只做含量计算"), self.model, self.root)
        self.assertNotEqual(result["status"], "unsupported")


if __name__ == "__main__":
    unittest.main()
