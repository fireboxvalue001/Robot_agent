import unittest
import json
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator
from backend.planner.model import deepseek_model
from backend.planner.service import PlannerService
from backend.planner.types import PlannerRequest, SampleParameters, TaskIntent


class PartialCoverageModel:
    def generate(self, messages, max_tokens=768):
        context = json.loads(messages[-1]["content"])
        steps = [{
            "operation_id": operation["operation_id"],
            "evidence_ids": [operation["evidence_id"]],
        } for operation in context["retrieved_operations"]]
        return json.dumps({
            "steps": steps,
            "unresolved_requests": [context["request"]["text"]],
        }, ensure_ascii=False), {
            "used": True,
            "runtime": "test_partial",
            "finish_reason": "stop",
            "network_inference": False,
        }


def request(**overrides):
    values = {
        "text": "将已交接样品送入VD10检测并读取结果",
        "knowledge_mode": "demo",
        "model_mode": "deterministic",
        "workflow_id": "wf_planner-test",
        "parameters": SampleParameters(
            sample_id="sample-001",
            handoff_confirmed=True,
            operator="tester",
        ),
        "read_results": True,
        "measurement_repeats": 1,
    }
    values.update(overrides)
    return PlannerRequest(**values)


class IntelligentPlannerTests(unittest.TestCase):
    def setUp(self):
        self.service = PlannerService()

    def test_current_capability_ids_form_ordered_plan(self):
        result = self.service.plan(request())

        self.assertEqual(result.status, "logical_pass")
        self.assertFalse(result.execution_allowed)
        self.assertEqual([step.operation_id for step in result.steps], [
            "robot.meta.receive_and_register_sample",
            "vd10.meta.prepare_test",
            "vd10.meta.sample_test",
            "vd10.meta.query_test_results",
            "robot.meta.read_result_from_screen",
        ])
        self.assertEqual(result.steps[-1].parameters["device_id"], "vd10")
        trace = result.reasoning_trace
        self.assertEqual(trace["trace_type"], "verified_decision_trace")
        self.assertEqual(trace["decision"]["status"], "PHYSICAL_PENDING")
        self.assertTrue(trace["decision"]["logical_executable"])
        self.assertEqual(len(trace["goals"]), 6)
        self.assertTrue(all(goal["status"] == "covered" for goal in trace["goals"]))
        self.assertEqual(len(trace["mappings"]), 5)
        self.assertTrue(all(
            value is True
            for key, value in trace["validation"].items()
            if key.endswith(("_valid", "_complete", "_closed"))
        ))
        self.assertEqual(
            trace["mappings"][0]["inputs"][0]["source"],
            "request.parameters.sample_id",
        )
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "schemas" / "reasoning-trace.schema.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(trace)), [])

    def test_unconfirmed_handoff_is_rejected_before_model_call(self):
        result = self.service.plan(request(parameters=SampleParameters(
            sample_id="sample-001", handoff_confirmed=False,
        )))
        self.assertEqual(result.status, "conflict")
        self.assertEqual(result.issues[0]["code"], "HANDOFF_NOT_CONFIRMED")
        self.assertFalse(result.generation["used"])
        self.assertEqual(result.reasoning_trace["decision"]["status"], "LOGICAL_BLOCKED")
        self.assertFalse(result.reasoning_trace["decision"]["logical_executable"])

    def test_missing_sample_id_still_produces_candidate_chain(self):
        result = self.service.plan(request(parameters=SampleParameters(handoff_confirmed=True)))
        self.assertEqual(result.status, "needs_input")
        self.assertEqual(result.issues[0]["code"], "DEFERRED_SAMPLE_ID")
        self.assertTrue(result.generation["used"])
        self.assertEqual(len(result.steps), 5)
        self.assertNotIn("sample_id", result.steps[0].parameters)
        self.assertFalse(result.reasoning_trace["validation"]["parameters_complete"])
        self.assertFalse(result.reasoning_trace["decision"]["logical_executable"])
        self.assertFalse(result.execution_allowed)
        self.assertEqual(result.reasoning_trace["goals"][0]["status"], "capability_matched")

    def test_operator_is_optional_for_planning(self):
        result = self.service.plan(request(parameters=SampleParameters(
            sample_id="sample-001", handoff_confirmed=True,
        )))
        self.assertEqual(result.status, "logical_pass")
        self.assertNotIn("operator", result.steps[1].parameters)

    def test_approved_mode_rejects_draft_knowledge(self):
        result = self.service.plan(request(knowledge_mode="approved_only"))
        self.assertEqual(result.status, "needs_review")
        self.assertEqual(result.issues[0]["code"], "NO_APPROVED_KNOWLEDGE")

    def test_result_steps_are_optional_when_not_requested(self):
        result = self.service.plan(request(read_results=False))
        self.assertEqual(result.status, "logical_pass")
        self.assertEqual([step.operation_id for step in result.steps], [
            "robot.meta.receive_and_register_sample",
            "vd10.meta.prepare_test",
            "vd10.meta.sample_test",
        ])
        self.assertEqual(len(result.reasoning_trace["goals"]), 4)
        self.assertEqual(len(result.reasoning_trace["mappings"]), 3)

    def test_partial_request_reports_covered_and_blocked_goals_separately(self):
        service = PlannerService(models={
            "deepseek": PartialCoverageModel(),
            "deterministic": self.service.models["deterministic"],
        })
        result = service.plan(request(
            model_mode="deepseek",
            text="将桌上的样品分成4份，每份25ml，分别送到四个仪器中进行检测",
        ))

        self.assertEqual(result.status, "unsupported")
        self.assertEqual(result.steps, [])
        goals = result.reasoning_trace["goals"]
        self.assertEqual(len(goals), 8)
        self.assertEqual(goals[0]["status"], "needs_input")
        self.assertEqual(goals[-2]["status"], "scenario_blocked")
        self.assertEqual(goals[-2]["candidate_operations"], ["robot.meta.aliquot_sample"])
        self.assertEqual(goals[-1]["status"], "needs_input")
        self.assertIn("稳定ID", goals[-1]["reason"])
        self.assertEqual([goal["status"] for goal in goals[1:6]], ["capability_matched"] * 5)
        self.assertFalse(result.reasoning_trace["validation"]["goal_coverage_complete"])
        self.assertEqual(len(result.reasoning_trace["mappings"]), 0)
        self.assertEqual(result.reasoning_trace["decision"]["status"], "UNSUPPORTED")
        self.assertFalse(result.generation["used"])

    def test_document_tests_are_checked_before_model_and_not_counted_as_vd10_steps(self):
        service = PlannerService(models={"deepseek": PartialCoverageModel()})
        result = service.plan(request(
            model_mode="deepseek",
            text="委托单TEST-01，样品HY-001，检测项目：运动黏度、颗粒计数、FTIR",
            task_intent=TaskIntent(
                source="document",
                requested_tests=["运动黏度（GB/T 265）", "颗粒计数（GB/T 14095）", "FTIR（GB/T 37280）"],
                missing_fields=["target_device"],
            ),
        ))
        self.assertEqual(result.status, "unsupported")
        self.assertEqual(result.steps, [])
        self.assertFalse(result.generation["used"])
        self.assertEqual([goal["status"] for goal in result.reasoning_trace["goals"][:3]], ["scenario_blocked"] * 3)
        self.assertEqual(result.reasoning_trace["goals"][0]["candidate_operations"], ["viscometer.meta.run_test"])
        self.assertEqual(result.reasoning_trace["goals"][1]["candidate_operations"], ["particle_counter.meta.run_test"])
        self.assertEqual(result.reasoning_trace["goals"][2]["candidate_operations"], ["ftir.meta.acquire_spectrum"])
        self.assertFalse(result.reasoning_trace["validation"]["goal_coverage_complete"])

    def test_mixed_supported_and_unsupported_tests_show_individual_matches(self):
        result = self.service.plan(request(
            text="检测项目：蒸馏特性、运动黏度",
            task_intent=TaskIntent(source="document", requested_tests=["蒸馏特性", "运动黏度"]),
        ))
        self.assertEqual(result.status, "unsupported")
        self.assertEqual(result.steps, [])
        goals = result.reasoning_trace["goals"]
        self.assertEqual(goals[0]["status"], "capability_matched")
        self.assertEqual(goals[1]["status"], "scenario_blocked")
        self.assertEqual([goal["status"] for goal in goals[2:]], ["capability_matched"] * 5)
        self.assertFalse(result.reasoning_trace["validation"]["goal_coverage_complete"])

    def test_structured_vd10_distillation_goal_is_covered(self):
        result = self.service.plan(request(
            text="对已交接样品进行VD10蒸馏检测并读取结果",
            task_intent=TaskIntent(source="document", requested_tests=["蒸馏特性（GB/T 6536）"], target_device="VD10"),
        ))
        self.assertEqual(result.status, "logical_pass")
        self.assertEqual(result.reasoning_trace["goals"][0]["status"], "covered")

    def test_missing_deepseek_key_is_not_replaced_by_offline_result(self):
        service = PlannerService(models={
            "deepseek": deepseek_model,
            "deterministic": self.service.models["deterministic"],
        })
        with patch.dict("os.environ", {"DEEPSEEK_API_KEY": ""}):
            result = service.plan(request(model_mode="deepseek"))
        self.assertEqual(result.status, "model_error")
        self.assertEqual(result.issues[0]["code"], "MODEL_UNAVAILABLE")
        self.assertEqual(result.steps, [])


if __name__ == "__main__":
    unittest.main()
