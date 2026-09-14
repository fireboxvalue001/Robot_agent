import base64
import os
import time
from dataclasses import dataclass

from fastapi import HTTPException
from tencentcloud.common import credential
from tencentcloud.common.common_client import CommonClient
from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
    TencentCloudSDKException,
)
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile


SUPPORTED_FORMATS = {
    "wav",
    "pcm",
    "ogg-opus",
    "speex",
    "silk",
    "mp3",
    "m4a",
    "aac",
    "amr",
}


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    request_id: str
    elapsed_ms: int
    voice_format: str


def detect_voice_format(filename: str, content: bytes) -> str:
    if content.startswith(b"\x1A\x45\xDF\xA3"):
        raise HTTPException(
            status_code=415,
            detail="WebM audio is not accepted. Record or convert the audio to WAV.",
        )

    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported audio format: {suffix or 'unknown'}.",
        )
    if suffix == "wav" and not content.startswith(b"RIFF"):
        raise HTTPException(status_code=415, detail="The uploaded WAV header is invalid.")
    return suffix


def transcribe_with_tencent_cloud(content: bytes, filename: str) -> TranscriptionResult:
    secret_id = os.getenv("TENCENTCLOUD_SECRET_ID", "").strip()
    secret_key = os.getenv("TENCENTCLOUD_SECRET_KEY", "").strip()
    if not secret_id or not secret_key:
        raise HTTPException(
            status_code=503,
            detail="Tencent Cloud ASR credentials are not configured in backend/.env.",
        )

    voice_format = detect_voice_format(filename, content)
    started_at = time.perf_counter()
    cred = credential.Credential(secret_id, secret_key)
    http_profile = HttpProfile()
    http_profile.endpoint = "asr.tencentcloudapi.com"
    client_profile = ClientProfile()
    client_profile.httpProfile = http_profile
    client = CommonClient(
        "asr",
        "2019-06-14",
        cred,
        os.getenv("TENCENTCLOUD_REGION", "").strip(),
        profile=client_profile,
    )
    params = {
        "SubServiceType": 2,
        "ProjectId": 0,
        "EngSerViceType": os.getenv("TENCENT_ASR_ENGINE", "16k_zh"),
        "SourceType": 1,
        "VoiceFormat": voice_format,
        "Data": base64.b64encode(content).decode("utf-8"),
        "DataLen": len(content),
        "FilterPunc": 0,
        "ConvertNumMode": 1,
    }

    try:
        response = client.call_json("SentenceRecognition", params)
    except TencentCloudSDKException as exc:
        provider_message = (
            getattr(exc, "message", None)
            or getattr(exc, "code", None)
            or str(exc)
        )
        raise HTTPException(
            status_code=502,
            detail=f"Tencent Cloud ASR failed: {provider_message}",
        ) from exc

    payload = response.get("Response", {})
    text = str(payload.get("Result", "")).strip()
    if not text:
        raise HTTPException(
            status_code=502,
            detail="Tencent Cloud ASR returned an empty transcription.",
        )

    return TranscriptionResult(
        text=text,
        request_id=str(payload.get("RequestId", "")),
        elapsed_ms=round((time.perf_counter() - started_at) * 1000),
        voice_format=voice_format,
    )
