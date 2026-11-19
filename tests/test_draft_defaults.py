import copy
import unittest

from backend.planner.conditional import plan_conditional, validate_scenario
from backend.planner.process_parameters import parse_explicit, verify_model_binding
from backend.planner.scenarios import load_config
from backend.planner.types import PlannerRequest


class DraftDefaultTests(unittest.TestCase):
    def test_defaults_are_offered_not_silently_applied(self):
        request = PlannerRequest(scenario_id="leather_fat_extraction", knowledge_mode="demo",
                                 model_mode="deterministic", text="执行一次完整的油脂提取实验")
        result = plan_conditional(request, None)
        workflow = result["workflow_definition"]
        fields = {item["field"]: item for item in workflow["clarifications"] if item["kind"] == "parameter"}
        self.assertEqual(fields["max_cycles"]["draft_default"], 5)
        self.assertNotIn("max_cycles", workflow["parameters"])
        self.assertTrue(all("draft_default" in item for item in fields.values()))
        self.assertFalse(workflow["execution_allowed"])
        text = request.text + "；" + "；".join(
            f"【草案默认值】{item['label']}：{item['draft_default']}{item['unit']}" for item in fields.values())
        result = plan_conditional(PlannerRequest(scenario_id=request.scenario_id, knowledge_mode="demo",
                                                model_mode="deterministic", text=text), None)
        workflow = result["workflow_definition"]
        self.assertFalse(any(item["kind"] == "parameter" for item in workflow["clarifications"]))
        self.assertFalse(any(item["kind"] == "method" for item in workflow["clarifications"]))
        self.assertEqual(result["status"], "logical_pass")
        self.assertTrue(result["reasoning_trace"]["decision"]["logical_executable"])
        self.assertEqual(workflow["method"]["review_status"], "draft")
        self.assertFalse(workflow["methods"]["solvent_removal_method"]["approved"])
        self.assertEqual(workflow["physical_requirements"][0]["status"], "pending")
        self.assertTrue(workflow["usage_prerequisites"])
        self.assertEqual(workflow["parameters"]["max_cycles"]["source"], "draft_default")
        self.assertFalse(workflow["execution_allowed"])

    def test_provenance_survives_ai_extraction(self):
        spec = {"label": "等待时长", "unit": "秒", "minimum": 1}
        text = "【草案默认值】等待时长：30秒"
        explicit, conflicts = parse_explicit(text, {"wait": spec})
        self.assertFalse(conflicts)
        binding = verify_model_binding("wait", {"value": 30, "quote": "等待时长：30秒", "token": "30"},
                                       spec, text, explicit)
        self.assertEqual(binding["source"], "draft_default")

    def test_generic_defaults_and_reject_bad_configuration(self):
        scenario = load_config("sample_hold_config")
        validate_scenario(scenario)
        self.assertNotIn("draft_default", scenario["parameters"]["label_confirmed"])
        self.assertNotIn("draft_default", scenario["parameters"]["sample_name"])
        bad = copy.deepcopy(scenario)
        bad["parameters"]["hold_seconds"]["draft_default"] = -1
        with self.assertRaises(ValueError):
            validate_scenario(bad)
        bad = copy.deepcopy(scenario)
        bad["parameters"]["label_confirmed"].update(draft_default=True, draft_default_note="不可默认通过")
        with self.assertRaises(ValueError):
            validate_scenario(bad)


if __name__ == "__main__":
    unittest.main()
