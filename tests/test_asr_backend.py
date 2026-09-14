import unittest

from fastapi import HTTPException

from backend.asr_service import detect_voice_format
from backend.server import (
    get_meta_operation_capabilities,
    get_frontend_asset,
    get_public_data,
    get_spatial_location_capabilities,
    health_check,
)


class AsrBackendTests(unittest.TestCase):
    def test_health_reports_asr_configuration_without_credentials(self):
        result = health_check()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["asr"]["provider"], "tencent_cloud")
        self.assertIsInstance(result["asr"]["configured"], bool)
        self.assertEqual(result["mqtt"]["topics"]["publish"], "autolab/ui/input")
        self.assertEqual(result["mqtt"]["topics"]["subscribe"], [
            "autolab/semantic/params",
            "autolab/planner/result",
            "autolab/physical/validation",
        ])

    def test_capability_endpoints_return_versioned_snapshots(self):
        operations = get_meta_operation_capabilities()
        self.assertEqual(operations["libraryId"], "autolab.vd10.meta_operations")
        self.assertEqual(operations["libraryVersion"], "1.3.0")
        self.assertTrue(operations["checksum"].startswith("sha256:"))
        self.assertEqual(len(operations["metaOperations"]), 35)

        spatial = get_spatial_location_capabilities()
        self.assertEqual(spatial["libraryId"], "autolab.multifloor_building")
        self.assertEqual(len(spatial["locations"]), 5)
        self.assertEqual(len(spatial["transportLinks"]), 1)

    def test_static_file_whitelist_blocks_private_files(self):
        with self.assertRaises(HTTPException) as env_error:
            get_frontend_asset(".env")
        self.assertEqual(env_error.exception.status_code, 404)
        with self.assertRaises(HTTPException) as history_error:
            get_public_data("mqtt_history.jsonl")
        self.assertEqual(history_error.exception.status_code, 404)

    def test_valid_wav_is_accepted(self):
        self.assertEqual(detect_voice_format("voice.wav", b"RIFF" + bytes(40)), "wav")

    def test_invalid_wav_header_is_rejected(self):
        with self.assertRaises(HTTPException) as context:
            detect_voice_format("voice.wav", b"not-a-wave")
        self.assertEqual(context.exception.status_code, 415)

    def test_webm_is_rejected_before_cloud_request(self):
        with self.assertRaises(HTTPException) as context:
            detect_voice_format("voice.webm", b"\x1A\x45\xDF\xA3" + bytes(20))
        self.assertEqual(context.exception.status_code, 415)


if __name__ == "__main__":
    unittest.main()
