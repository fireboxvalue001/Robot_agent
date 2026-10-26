import copy
import json
import unittest
from pathlib import Path

from fastapi import HTTPException
from backend.local_semantic_adapter import resolve_local_semantic as plan_local_semantic
from backend.server import app, plan_from_local_semantic


ROOT = Path(__file__).resolve().parent.parent


class LocalSemanticAdapterTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads((ROOT / "examples/local-semantic-add.sample.json").read_text(encoding="utf-8"))
        self.arguments = self.payload["parameters"]["operations"][0]["arguments"]

    def check_contract(self, result):
        self.assertEqual(result["type"], "resolved_intent")
        self.assertNotIn("operationChain", result)
        self.assertNotIn("steps", result)
        self.assertNotIn("reasoning_trace", result)

    def check_blocked(self, field):
        result = plan_local_semantic(self.payload)
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("operationChain", result)
        self.assertIn(field, result["preprocessing"]["clarification"]["missingFields"])
        self.assertIsNone(result["resolvedText"])
        self.check_contract(result)

    def test_exact_colleague_payload_maps_ids_and_recovers_only_volume(self):
        original = copy.deepcopy(self.payload)
        result = plan_local_semantic(self.payload)
        self.assertEqual(result["status"], "success")
        fields = result["preprocessing"]["parameters"]
        self.assertEqual(fields["source_object_id"]["value"], "bottle_1")
        self.assertEqual(fields["target_object_id"]["value"], "bottle_2")
        self.assertEqual(fields["volume_ml"]["value"], 10)
        self.assertEqual(result["adapterMetadata"]["parameterSources"]["volume_ml"], "originalText")
        self.assertEqual(result["adapterMetadata"]["sourceOperationId"], "op_001")
        self.assertEqual(self.payload, original)
        self.assertEqual(result["sourceSemantic"], original)
        self.assertFalse(result["execution_allowed"])
        self.assertEqual(result["physical_status"], "not_evaluated")
        self.assertEqual(result["resolvedText"], "从瓶子1（容器编号：bottle_1）中吸取10mL液体，加入瓶子2（容器编号：bottle_2）中。")
        self.assertEqual(result["preprocessing"]["originalText"], result["resolvedText"])
        self.check_contract(result)

    def test_structured_volume_without_text_quantity(self):
        self.payload["originalText"] = "从瓶子1移液至瓶子2"
        self.arguments["volume"] = {"value": 2.5, "unit": "mL"}
        result = plan_local_semantic(self.payload)
        self.assertEqual(result["status"], "success")
        self.assertIn("吸取2.5mL", result["resolvedText"])
        self.assertIn("arguments.volume", result["adapterMetadata"]["parameterSources"]["volume_ml"])
        self.check_contract(result)

    def test_missing_quantity_is_not_recovered_from_description(self):
        self.payload["originalText"] = "把这个加到这个里面"
        self.payload["parameters"]["operationDescription"] = "加入10ml"
        self.check_blocked("volume")

    def test_text_and_structured_volume_conflict(self):
        self.arguments["volume"] = {"value": 25, "unit": "mL"}
        self.check_blocked("volume")

    def test_nonpositive_or_ambiguous_text_quantity(self):
        for text in ["加入0ml", "加入-10ml", "加入−10ml", "加入10ml，再加入5ml", "加入10ml与10ml"]:
            with self.subTest(text=text):
                self.payload["originalText"] = text
                self.check_blocked("volume")

    def test_boolean_wrong_unit_and_nonfinite_volume(self):
        for volume in [{"value": True, "unit": "mL"}, {"value": 10, "unit": "L"}, {"value": float("inf"), "unit": "mL"}]:
            with self.subTest(volume=volume):
                self.arguments["volume"] = volume
                self.check_blocked("volume")

    def test_missing_object_id_and_same_container_are_blocked(self):
        self.arguments["targetObject"]["objectId"] = ""
        self.check_blocked("targetObject")
        self.arguments["targetObject"]["objectId"] = "bottle_1"
        self.check_blocked("targetObject")

    def test_unresolved_and_processing_results_do_not_create_chain(self):
        self.payload["parameters"]["unresolved"] = ["目标容器未确认"]
        self.check_blocked("unresolved")
        self.payload["parameters"]["unresolved"] = []
        self.payload["status"] = "processing"
        self.check_blocked("status")

    def test_unsupported_action_and_multiple_operations(self):
        self.payload["parameters"]["operations"][0]["action"] = "move"
        self.check_blocked("action")
        self.payload["parameters"]["operations"].append(copy.deepcopy(self.payload["parameters"]["operations"][0]))
        self.check_blocked("operations")

    def test_local_http_accepts_bare_json_and_preserves_optional_workflow_id(self):
        self.payload["workflowId"] = "wf_local-test"
        self.assertTrue(any(route.path == "/api/v1/intent/from-semantic" and "POST" in route.methods for route in app.routes))
        result = plan_from_local_semantic(self.payload)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["workflowId"], "wf_local-test")
        self.check_contract(result)

    def test_invalid_workflow_id_returns_http_validation_error(self):
        self.payload["workflowId"] = "wrong"
        with self.assertRaises(HTTPException) as caught:
            plan_from_local_semantic(self.payload)
        self.assertEqual(caught.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
