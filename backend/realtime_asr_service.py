import base64
import hashlib
import hmac
import json
import os
import random
import time
import uuid
from urllib.parse import quote, urlencode


TENCENT_ASR_HOST = "asr.cloud.tencent.com"


class RealtimeAsrConfigurationError(RuntimeError):
    pass


def realtime_asr_configured() -> bool:
    return all(
        os.getenv(name, "").strip()
        for name in (
            "TENCENTCLOUD_APP_ID",
            "TENCENTCLOUD_SECRET_ID",
            "TENCENTCLOUD_SECRET_KEY",
        )
    )


def build_realtime_asr_url(
    *,
    now: int | None = None,
    nonce: int | None = None,
    voice_id: str | None = None,
) -> tuple[str, str]:
    app_id = os.getenv("TENCENTCLOUD_APP_ID", "").strip()
    secret_id = os.getenv("TENCENTCLOUD_SECRET_ID", "").strip()
    secret_key = os.getenv("TENCENTCLOUD_SECRET_KEY", "").strip()
    if not app_id or not secret_id or not secret_key:
        raise RealtimeAsrConfigurationError(
            "Tencent realtime ASR requires TENCENTCLOUD_APP_ID, "
            "TENCENTCLOUD_SECRET_ID and TENCENTCLOUD_SECRET_KEY."
        )

    timestamp = int(time.time()) if now is None else int(now)
    current_voice_id = voice_id or str(uuid.uuid4())
    params = {
        "engine_model_type": os.getenv("TENCENT_ASR_ENGINE", "16k_zh"),
        "expired": timestamp + 86400,
        "filter_punc": 0,
        "convert_num_mode": 1,
        "needvad": 1,
        "nonce": nonce if nonce is not None else random.randint(100000, 9999999999),
        "secretid": secret_id,
        "timestamp": timestamp,
        "vad_silence_time": int(os.getenv("TENCENT_ASR_VAD_SILENCE_TIME", "800")),
        "voice_format": 1,
        "voice_id": current_voice_id,
        "word_info": int(os.getenv("TENCENT_ASR_WORD_INFO", "1")),
    }
    query = urlencode(sorted(params.items()))
    path = f"/asr/v2/{app_id}"
    sign_source = f"{TENCENT_ASR_HOST}{path}?{query}"
    digest = hmac.new(
        secret_key.encode("utf-8"), sign_source.encode("utf-8"), hashlib.sha1
    ).digest()
    signature = quote(base64.b64encode(digest).decode("ascii"), safe="")
    return f"wss://{TENCENT_ASR_HOST}{path}?{query}&signature={signature}", current_voice_id


def normalize_provider_message(payload: dict, stream_started_at: int) -> dict | None:
    code = int(payload.get("code") or 0)
    if code != 0:
        return {
            "type": "error",
            "code": code,
            "message": str(payload.get("message") or "Tencent realtime ASR failed."),
        }

    result = payload.get("result")
    if not isinstance(result, dict):
        return None

    start_offset = int(result.get("start_time") or 0)
    end_offset = int(result.get("end_time") or start_offset)
    words = []
    for item in result.get("word_list") or []:
        if not isinstance(item, dict) or not item.get("word"):
            continue
        word_start = int(item.get("start_time") or 0)
        word_end = int(item.get("end_time") or word_start)
        words.append(
            {
                "text": str(item["word"]),
                "startOffsetMs": word_start,
                "endOffsetMs": word_end,
                "startedAt": stream_started_at + word_start,
                "endedAt": stream_started_at + word_end,
                "stable": bool(item.get("stable_flag", 1)),
            }
        )

    slice_type = int(result.get("slice_type") or 0)
    return {
        "type": "sentence",
        "voiceId": str(payload.get("voice_id") or ""),
        "index": int(result.get("index") or 0),
        "final": slice_type == 2,
        "sliceType": slice_type,
        "text": str(result.get("voice_text_str") or "").strip(),
        "startOffsetMs": start_offset,
        "endOffsetMs": end_offset,
        "startedAt": stream_started_at + start_offset,
        "endedAt": stream_started_at + end_offset,
        "words": words,
    }


def decode_provider_message(message: str | bytes) -> dict:
    if isinstance(message, bytes):
        message = message.decode("utf-8")
    return json.loads(message)


def provider_message_is_final(payload: dict) -> bool:
    return int(payload.get("final") or 0) == 1
