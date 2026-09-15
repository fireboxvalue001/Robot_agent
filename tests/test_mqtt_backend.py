import os
import tempfile
import unittest
from unittest.mock import patch

import paho.mqtt.client as mqtt

from backend.mqtt_service import (
    TOPIC_PHYSICAL_VALIDATION,
    TOPIC_PLANNER_RESULT,
    TOPIC_SEMANTIC_PARAMS,
    TOPIC_UI_INPUT,
    MqttService,
    get_capability_identity,
    validate_physical_validation,
    validate_planner_message,
    validate_semantic_message,
)


class FakePublishInfo:
    rc = mqtt.MQTT_ERR_SUCCESS


class FakeClient:
    def __init__(self):
        self.calls = []

    def publish(self, topic, payload, qos, retain):
        self.calls.append({"topic": topic, "payload": payload, "qos": qos, "retain": retain})
        return FakePublishInfo()


class MqttBackendTests(unittest.TestCase):
    def setUp(self):
        self.history_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.history_dir.cleanup)

    def make_service(self):
        with patch.dict(os.environ, {
            "MQTT_ENABLED": "true",
            "MQTT_QOS": "0",
            "MQTT_HISTORY_DIR": self.history_dir.name,
        }):
            service = MqttService()
        service._client = FakeClient()
        service._connected.set()
        return service

    def test_ui_input_preserves_upstream_message_contract(self):
        service = self.make_service()
        record = service.publish_ui_input("  分装4份样品  ")
        message = record["ui_input"]

        self.assertEqual(service._client.calls[0]["topic"], TOPIC_UI_INPUT)
        self.assertFalse(service._client.calls[0]["retain"])
        self.assertEqual(
            set(message),
            {"msgId", "type", "author", "workflowId", "index", "status", "history", "text", "timestamp"},
        )
        self.assertEqual(message["type"], "ui_input")
        self.assertEqual(message["index"], 0)
        self.assertEqual(message["status"], "processing")
        self.assertEqual(message["history"], [])
        self.assertEqual(message["text"], "分装4份样品")

    def test_semantic_result_is_correlated_by_workflow_id(self):
        service = self.make_service()
        record = service.publish_ui_input("分装4份样品")
        message = {
            "msgId": "msg_semantic-test",
            "type": "semantic_params",
            "author": "semantic",
            "workflowId": record["workflowId"],
            "index": 1,
            "status": "success",
            "history": [],
            "originalText": "分装4份样品",
            "parameters": {"count": {"type": "number", "value": 4, "unit": "份"}},
            "timestamp": 1788480001000,
        }

        accepted, error = service.accept_semantic_message(message)
        self.assertTrue(accepted)
        self.assertIsNone(error)
        updated = service.get_workflow(record["workflowId"])
        self.assertEqual(updated["state"], "semantic_received")
        self.assertEqual(updated["semantic_params"], message)
        history = service.query_history(workflow_id=record["workflowId"])
        self.assertEqual([item["event"] for item in history], [
            "semantic_params_received",
            "ui_input_published",
        ])

        accepted, error = service.accept_semantic_message(message)
        self.assertFalse(accepted)
        self.assertEqual(error, "duplicate_msg_id")

    def test_asr_timing_is_published_with_transcribed_text(self):
        service = self.make_service()
        timing = {
            "utteranceStartedAt": 1789091998000,
            "utteranceEndedAt": 1789092001000,
            "recognitionCompletedAt": 1789092004800,
            "audioDurationMs": 3000,
            "timeUnit": "unix_ms",
        }

        record = service.publish_ui_input(
            "将样品送到VD10进行检测",
            asr_timing=timing,
        )

        self.assertEqual(record["ui_input"]["asrTiming"], timing)
        self.assertEqual(record["ui_input"]["text"], "将样品送到VD10进行检测")

    def test_invalid_asr_timing_is_rejected(self):
        service = self.make_service()
        timing = {
            "utteranceStartedAt": 2000,
            "utteranceEndedAt": 1000,
            "recognitionCompletedAt": 3000,
            "audioDurationMs": 0,
            "timeUnit": "unix_ms",
        }

        with self.assertRaisesRegex(ValueError, "end must not precede"):
            service.publish_ui_input("无效时间", asr_timing=timing)

    def test_asr_timing_accepts_optional_sentence_and_word_details(self):
        timing = {
            "utteranceStartedAt": 1789196371200,
            "utteranceEndedAt": 1789196372600,
            "recognitionCompletedAt": 1789196372800,
            "audioDurationMs": 1400,
            "timeUnit": "unix_ms",
            "serviceStartedAt": 1789196370000,
            "streamStartedAt": 1789196370100,
            "sentences": [{
                "sentenceId": "utt_001", "index": 0,
                "text": "将样品送到VD10。",
                "startedAt": 1789196371200,
                "endedAt": 1789196372600,
                "words": [{
                    "text": "样品", "startedAt": 1789196371450,
                    "endedAt": 1789196371810,
                }],
            }],
        }

        service = self.make_service()
        record = service.publish_ui_input("将样品送到VD10。", asr_timing=timing)

        self.assertEqual(record["ui_input"]["asrTiming"], timing)

    def test_invalid_semantic_payload_is_rejected_without_transformation(self):
        self.assertEqual(validate_semantic_message({"type": "semantic_params"}).split(":")[0], "missing_fields")

    def test_topics_are_exactly_the_upstream_topics(self):
        self.assertEqual(TOPIC_UI_INPUT, "autolab/ui/input")
        self.assertEqual(TOPIC_SEMANTIC_PARAMS, "autolab/semantic/params")
        self.assertEqual(TOPIC_PLANNER_RESULT, "autolab/planner/result")
        self.assertEqual(TOPIC_PHYSICAL_VALIDATION, "autolab/physical/validation")

    def test_planner_and_physical_results_are_correlated(self):
        service = self.make_service()
        workflow = service.publish_ui_input("将样品送到VD10检测")
        workflow_id = workflow["workflowId"]
        planner = {
            "msgId": "msg_planner-test", "type": "planner_result", "author": "planner",
            "workflowId": workflow_id, "index": 2, "status": "success", "history": [],
            "experimentName": "VD10检测", "steps": [{"step": 1, "action": "VD10样品检测"}],
            "parameters": {}, "timestamp": 1788480002000,
            "operationChain": {
                "contractVersion": "1.0.0", "planId": "plan_test",
                "capabilityLibrary": get_capability_identity(),
                "operations": [{
                    "stepId": "step_001", "sequence": 1,
                    "metaOperationId": "vd10.meta.sample_test", "metaOperationVersion": "1.0.0",
                    "arguments": {}, "dependsOn": []
                }]
            }
        }
        accepted, error = service.accept_planner_message(planner)
        self.assertTrue(accepted)
        self.assertIsNone(error)
        self.assertEqual(service.get_workflow(workflow_id)["planner_result"], planner)

        physical = {
            "msgId": "msg_physical-test", "type": "physical_validation", "author": "physical_validator",
            "workflowId": workflow_id, "index": 3, "status": "success", "history": [],
            "planId": "plan_test", "result": "blocked", "timestamp": 1788480003000,
            "stepResults": [{
                "stepId": "step_001", "executable": False, "checks": [],
                "blockers": ["设备状态未确认"]
            }]
        }
        accepted, error = service.accept_physical_validation(physical)
        self.assertTrue(accepted)
        self.assertIsNone(error)
        updated = service.get_workflow(workflow_id)
        self.assertEqual(updated["state"], "physical_validation_received")
        self.assertEqual(updated["physical_validation"], physical)

    def test_successful_planner_result_requires_operation_chain(self):
        payload = {
            "msgId": "msg_missing-chain", "type": "planner_result", "author": "planner",
            "workflowId": "wf_test", "index": 2, "status": "success", "history": [],
            "experimentName": "test", "steps": [], "parameters": {}, "timestamp": 1
        }
        self.assertEqual(validate_planner_message(payload), "missing_operation_chain")

    def test_physical_validation_rejects_invalid_result(self):
        payload = {
            "msgId": "msg_physical", "type": "physical_validation", "author": "validator",
            "workflowId": "wf_test", "index": 3, "status": "success", "history": [],
            "planId": "plan_test", "result": "maybe", "stepResults": [], "timestamp": 1
        }
        self.assertEqual(validate_physical_validation(payload), "invalid_physical_result")

    def test_history_can_be_read_by_a_new_service_instance(self):
        service = self.make_service()
        record = service.publish_ui_input("跨重启记录测试")

        restarted_service = self.make_service()
        history = restarted_service.query_history(workflow_id=record["workflowId"])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["payload"], record["ui_input"])


if __name__ == "__main__":
    unittest.main()
