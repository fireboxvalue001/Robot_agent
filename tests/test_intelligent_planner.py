import unittest
from unittest.mock import patch

from backend.planner.model import deepseek_model
from backend.planner.service import PlannerService
from backend.planner.types import PlannerRequest, SampleParameters


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

    def test_unconfirmed_handoff_is_rejected_before_model_call(self):
        result = self.service.plan(request(parameters=SampleParameters(
            sample_id="sample-001", handoff_confirmed=False,
        )))
        self.assertEqual(result.status, "conflict")
        self.assertEqual(result.issues[0]["code"], "HANDOFF_NOT_CONFIRMED")
        self.assertFalse(result.generation["used"])

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
