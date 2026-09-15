import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from backend.realtime_asr_service import (
    build_realtime_asr_url,
    normalize_provider_message,
    provider_message_is_final,
    realtime_asr_configured,
)


class RealtimeAsrTests(unittest.TestCase):
    def test_signed_url_contains_realtime_parameters(self):
        environment = {
            "TENCENTCLOUD_APP_ID": "1234567890",
            "TENCENTCLOUD_SECRET_ID": "test-secret-id",
            "TENCENTCLOUD_SECRET_KEY": "test-secret-key",
            "TENCENT_ASR_ENGINE": "16k_zh",
            "TENCENT_ASR_WORD_INFO": "1",
            "TENCENT_ASR_VAD_SILENCE_TIME": "800",
        }
        with patch.dict(os.environ, environment, clear=True):
            url, voice_id = build_realtime_asr_url(
                now=1700000000, nonce=123456, voice_id="voice-test"
            )

        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.scheme, "wss")
        self.assertEqual(parsed.path, "/asr/v2/1234567890")
        self.assertEqual(voice_id, "voice-test")
        self.assertEqual(query["needvad"], ["1"])
        self.assertEqual(query["word_info"], ["1"])
        self.assertEqual(query["vad_silence_time"], ["800"])
        self.assertIn("signature", query)

    def test_provider_offsets_are_converted_to_unix_milliseconds(self):
        provider_message = {
            "code": 0,
            "voice_id": "voice-test",
            "result": {
                "slice_type": 2,
                "index": 3,
                "start_time": 1200,
                "end_time": 2600,
                "voice_text_str": "将样品送到VD10。",
                "word_list": [{
                    "word": "样品", "start_time": 1450,
                    "end_time": 1810, "stable_flag": 1,
                }],
            },
        }

        result = normalize_provider_message(provider_message, 1789196370000)

        self.assertTrue(result["final"])
        self.assertEqual(result["startedAt"], 1789196371200)
        self.assertEqual(result["endedAt"], 1789196372600)
        self.assertEqual(result["words"][0]["startedAt"], 1789196371450)
        self.assertEqual(result["words"][0]["endedAt"], 1789196371810)

    def test_realtime_requires_app_id_in_addition_to_existing_credentials(self):
        with patch.dict(os.environ, {
            "TENCENTCLOUD_SECRET_ID": "id",
            "TENCENTCLOUD_SECRET_KEY": "key",
        }, clear=True):
            self.assertFalse(realtime_asr_configured())

    def test_provider_final_event_is_a_clean_session_end(self):
        self.assertTrue(provider_message_is_final({"code": 0, "final": 1}))
        self.assertFalse(provider_message_is_final({"code": 0, "final": 0}))


if __name__ == "__main__":
    unittest.main()
