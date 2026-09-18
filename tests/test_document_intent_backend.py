import asyncio
import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator
from starlette.datastructures import UploadFile

from backend.document_intent.router import recognize_document_intent
from backend.document_intent.service import (
    _provider_settings,
    extract_document_text,
    normalize_intent,
    to_semantic_params,
)


ROOT = Path(__file__).resolve().parents[1]


def raw_intent(test_name="蒸馏特性", standard="GB/T 6536"):
    return {
        "document_id": "DOC-001",
        "intent": "oil_analysis",
        "sample": {
            "oil_name": "液压油",
            "oil_type": "L-HM 46",
            "sample_no": "SAMPLE-001",
            "quantity_text": "2瓶，共200mL",
            "container_count": 2,
            "total_volume_ml": 200,
        },
        "tests": [{"name": test_name, "standard": standard}],
        "instruments": ["VD10"],
        "report_requirements": None,
        "constraints": None,
        "unresolved": None,
        "confidence": 0.91,
    }


class DocumentIntentTests(unittest.TestCase):
    def test_supported_distillation_routes_to_vd10(self):
        intent = normalize_intent(raw_intent(), "commission.txt")

        self.assertEqual(intent["instruments"], ["VD10"])
        self.assertEqual(intent["capability_assessment"]["routing_status"], "matched")
        self.assertEqual(intent["constraints"], [])
        self.assertEqual(intent["unresolved"], [])

    def test_unsupported_test_is_not_forced_to_vd10(self):
        intent = normalize_intent(raw_intent("运动黏度", "GB/T 265"), "commission.txt")

        self.assertEqual(intent["instruments"], [])
        self.assertEqual(intent["capability_assessment"]["routing_status"], "needs_routing")
        self.assertIn("运动黏度", intent["capability_assessment"]["unsupported_tests"])
        self.assertTrue(any("重新进行仪器路由" in item for item in intent["unresolved"]))

    def test_legacy_field_shapes_are_normalized(self):
        raw = raw_intent()
        raw["tests"] = ["馏程"]
        raw["constraints"] = "加急"
        raw["unresolved"] = "确认样品量"
        raw["report_requirements"] = ["电子报告"]

        intent = normalize_intent(raw, "commission.txt")

        self.assertEqual(intent["tests"][0]["name"], "馏程")
        self.assertEqual(intent["constraints"], ["加急"])
        self.assertEqual(intent["unresolved"], ["确认样品量"])
        self.assertEqual(intent["report_requirements"]["notes"], ["电子报告"])

    def test_model_aliases_and_quantity_text_are_normalized(self):
        raw = raw_intent()
        raw["sample"] = {
            "sample_id": "OIL-D86-001",
            "name": "液压油",
            "specification": "L-HM 46",
            "quantity": "2瓶，共200 mL",
        }
        raw["tests"] = [{"test_name": "蒸馏特性", "standard": "GB/T 6536"}]

        intent = normalize_intent(raw, "commission.txt")

        self.assertEqual(intent["sample"]["sample_no"], "OIL-D86-001")
        self.assertEqual(intent["sample"]["oil_name"], "液压油")
        self.assertEqual(intent["sample"]["oil_type"], "L-HM 46")
        self.assertEqual(intent["sample"]["container_count"], 2)
        self.assertEqual(intent["sample"]["total_volume_ml"], 200)
        self.assertEqual(intent["tests"][0]["name"], "蒸馏特性")
        self.assertEqual(intent["instruments"], ["VD10"])

    def test_semantic_adapter_matches_existing_contract(self):
        intent = normalize_intent(raw_intent(), "commission.txt")
        semantic = to_semantic_params(intent, source_text="委托单文字", workflow_id="wf_doc-test")
        schema = json.loads((ROOT / "schemas" / "semantic-params.schema.json").read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(semantic))

        self.assertEqual(errors, [])
        self.assertEqual(semantic["workflowId"], "wf_doc-test")
        self.assertEqual(semantic["parameters"]["target_device"]["value"], "VD10")
        self.assertFalse(semantic["clarification"]["needed"])

    def test_semantic_adapter_blocks_unmatched_instrument(self):
        intent = normalize_intent(raw_intent("运动黏度", "GB/T 265"), "commission.txt")
        semantic = to_semantic_params(intent, source_text="委托单文字")

        self.assertNotIn("target_device", semantic["parameters"])
        self.assertIn("target_device", semantic["clarification"]["missingFields"])
        self.assertTrue(semantic["clarification"]["needed"])

    def test_txt_extraction_supports_utf8_bom(self):
        self.assertEqual(extract_document_text("委托单".encode("utf-8-sig"), "sample.txt"), "委托单")

    def test_blank_override_config_uses_deepseek_defaults(self):
        with patch.dict(os.environ, {
            "DOCUMENT_INTENT_API_KEY": "",
            "DASHSCOPE_API_KEY": "",
            "DEEPSEEK_API_KEY": "key",
            "DOCUMENT_INTENT_MODEL": "",
            "DEEPSEEK_BASE_URL": "",
            "DEEPSEEK_MODEL": "",
        }, clear=False):
            settings = _provider_settings()

        self.assertEqual(settings["provider"], "deepseek")
        self.assertEqual(settings["model"], "deepseek-chat")
        self.assertEqual(settings["base_url"], "https://api.deepseek.com")

    def test_upload_adapter_returns_intent_and_semantic_contract(self):
        normalized = normalize_intent(raw_intent(), "commission.txt")
        upload = UploadFile(filename="commission.txt", file=io.BytesIO(b"document"))
        with patch("backend.document_intent.router.recognize_document", return_value={
            "text": "委托单文字",
            "intent": normalized,
        }):
            response = asyncio.run(recognize_document_intent(upload, workflow_id="wf_upload-test"))

        self.assertTrue(response["success"])
        self.assertEqual(response["intent"]["instruments"], ["VD10"])
        self.assertEqual(response["semanticParams"]["workflowId"], "wf_upload-test")


if __name__ == "__main__":
    unittest.main()
