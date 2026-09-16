import asyncio
import os
import hashlib
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .asr_service import detect_voice_format, transcribe_with_tencent_cloud
from .mqtt_service import mqtt_service
from .planning_service import plan_natural_language
from .planner.router import planner_runtime_status, router as planner_router
from .realtime_asr_service import (
    RealtimeAsrConfigurationError,
    build_realtime_asr_url,
    decode_provider_message,
    normalize_provider_message,
    provider_message_is_final,
    realtime_asr_configured,
)


BACKEND_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")

MAX_AUDIO_SIZE = 3 * 1024 * 1024
META_OPERATION_LIBRARY = FRONTEND_DIR / "data" / "meta-operations.json"
SPATIAL_LOCATION_LIBRARY = FRONTEND_DIR / "data" / "spatial-locations.json"
PUBLIC_ASSETS = {
    "app.js", "index.html", "meta-operation.css", "mqtt-input.js",
    "planner-controls.css", "styles.css", "voice-input.js",
}
PUBLIC_DATA_FILES = {
    "meta-operations.json", "spatial-locations.json", "vd10_agent_only_operation_tree.json",
}


@asynccontextmanager
async def lifespan(application: FastAPI):
    mqtt_service.start()
    yield
    mqtt_service.stop()


app = FastAPI(title="VD10 Visual Workflow with ASR and MQTT", version="0.3.0", lifespan=lifespan)
app.include_router(planner_router)


class AsrTimingRequest(BaseModel):
    utteranceStartedAt: int = Field(ge=0)
    utteranceEndedAt: int = Field(ge=0)
    recognitionCompletedAt: int = Field(ge=0)
    audioDurationMs: int = Field(ge=0)
    timeUnit: str = Field(pattern="^unix_ms$")
    serviceStartedAt: int | None = Field(default=None, ge=0)
    streamStartedAt: int | None = Field(default=None, ge=0)
    sentences: list[dict] | None = None


class UiInputRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    asrTiming: AsrTimingRequest | None = None


class NaturalLanguagePlanningRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    workflowId: str | None = Field(default=None, pattern=r"^wf_")


def capability_snapshot(path: Path, item_key: str) -> dict:
    raw = path.read_bytes()
    library = json.loads(raw.decode("utf-8"))
    return {
        "libraryId": library.get("library_id") or library.get("map_id"),
        "libraryVersion": library.get("schema_version"),
        "checksum": f"sha256:{hashlib.sha256(raw).hexdigest()}",
        "updatedAt": library.get("updated_at"),
        "categories": library.get("categories", []),
        "instruments": library.get("instruments", []),
        "preconditions": library.get("preconditions", []),
        item_key: library.get("meta_operations" if item_key == "metaOperations" else "locations", []),
        "transportLinks": library.get("transport_links", []) if item_key == "locations" else [],
        "coordinateFrame": library.get("coordinate_frame") if item_key == "locations" else None,
        "building": library.get("building") if item_key == "locations" else None,
    }


@app.get("/api/health")
def health_check() -> dict:
    return {
        "status": "ok",
        "asr": {
            "provider": "tencent_cloud",
            "configured": bool(
                os.getenv("TENCENTCLOUD_SECRET_ID")
                and os.getenv("TENCENTCLOUD_SECRET_KEY")
            ),
            "engine": os.getenv("TENCENT_ASR_ENGINE", "16k_zh"),
            "realtimeConfigured": realtime_asr_configured(),
        },
        "mqtt": mqtt_service.status(),
        "planner": planner_runtime_status(),
    }


@app.get("/api/v1/capabilities/meta-operations")
def get_meta_operation_capabilities() -> dict:
    return capability_snapshot(META_OPERATION_LIBRARY, "metaOperations")


@app.get("/api/v1/capabilities/spatial-locations")
def get_spatial_location_capabilities() -> dict:
    return capability_snapshot(SPATIAL_LOCATION_LIBRARY, "locations")


@app.post("/api/v1/planning/from-text")
def plan_from_natural_language(request: NaturalLanguagePlanningRequest) -> dict:
    return plan_natural_language(request.text, workflow_id=request.workflowId)


@app.post("/api/asr/transcribe")
async def transcribe_audio(audio: UploadFile = File(...)) -> dict:
    started_at = time.perf_counter()
    filename = audio.filename or "recording.wav"
    content = await audio.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded audio file is empty.")
    if len(content) > MAX_AUDIO_SIZE:
        raise HTTPException(status_code=413, detail="The audio file is larger than 3 MB.")

    detect_voice_format(filename, content)
    result = transcribe_with_tencent_cloud(content, filename)
    return {
        "success": True,
        "text": result.text,
        "request_id": result.request_id,
        "audio": {
            "size": len(content),
            "format": result.voice_format,
            "duration_ms": result.audio_duration_ms,
        },
        "words": result.words,
        "timing": {
            "provider_elapsed_ms": result.elapsed_ms,
            "total_elapsed_ms": round((time.perf_counter() - started_at) * 1000),
        },
    }


@app.websocket("/api/asr/realtime")
async def realtime_transcription(websocket: WebSocket) -> None:
    await websocket.accept()
    provider = None
    sender_task = None
    receiver_task = None
    try:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError(
                "The websockets dependency is missing. Run setup-asr.bat again."
            ) from exc

        provider_url, voice_id = build_realtime_asr_url()
        provider = await asyncio.wait_for(
            websockets.connect(provider_url, max_size=2 * 1024 * 1024),
            timeout=12,
        )
        handshake = decode_provider_message(
            await asyncio.wait_for(provider.recv(), timeout=12)
        )
        if int(handshake.get("code") or 0) != 0:
            raise RuntimeError(
                str(handshake.get("message") or "Tencent realtime ASR handshake failed.")
            )

        await websocket.send_json(
            {"type": "service_ready", "voiceId": voice_id, "timeUnit": "unix_ms"}
        )
        start_message = await websocket.receive_json()
        if start_message.get("type") != "start":
            raise ValueError("The first realtime ASR message must have type=start.")
        stream_started_at = int(start_message.get("streamStartedAt") or 0)
        if stream_started_at <= 0:
            raise ValueError("streamStartedAt must be a positive Unix millisecond timestamp.")

        async def send_audio_to_provider() -> str:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return "disconnect"
                audio = message.get("bytes")
                if audio is not None:
                    if audio:
                        await provider.send(audio)
                    continue
                raw = message.get("text")
                if raw is None:
                    continue
                command = json.loads(raw)
                if command.get("type") == "end":
                    await provider.send(json.dumps({"type": "end"}))
                    return "end"

        async def forward_provider_results() -> None:
            async for raw_message in provider:
                payload = decode_provider_message(raw_message)
                normalized = normalize_provider_message(payload, stream_started_at)
                if normalized is not None:
                    normalized["recognitionCompletedAt"] = int(time.time() * 1000)
                    await websocket.send_json(normalized)
                # Tencent may drop the TCP connection without a WebSocket close frame
                # after this event, so treat final=1 as the authoritative clean end.
                if provider_message_is_final(payload):
                    return

        sender_task = asyncio.create_task(send_audio_to_provider())
        receiver_task = asyncio.create_task(forward_provider_results())
        done, _ = await asyncio.wait(
            {sender_task, receiver_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if sender_task in done and sender_task.result() == "end":
            await asyncio.wait_for(receiver_task, timeout=12)
        elif receiver_task in done:
            await receiver_task
        await websocket.send_json({"type": "session_ended", "voiceId": voice_id})
    except WebSocketDisconnect:
        pass
    except (RealtimeAsrConfigurationError, ValueError, RuntimeError) as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except RuntimeError:
            pass
    except Exception as exc:
        try:
            await websocket.send_json(
                {"type": "error", "message": f"Realtime ASR failed: {exc}"}
            )
        except RuntimeError:
            pass
    finally:
        for task in (sender_task, receiver_task):
            if task is not None and not task.done():
                task.cancel()
        if provider is not None:
            await provider.close()


@app.post("/api/mqtt/ui-input")
def publish_ui_input(request: UiInputRequest) -> dict:
    try:
        asr_timing = request.asrTiming.model_dump() if request.asrTiming else None
        record = mqtt_service.publish_ui_input(request.text, asr_timing=asr_timing)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "success": True,
        "topic": "autolab/ui/input",
        "workflowId": record["workflowId"],
        "message": record["ui_input"],
    }


@app.get("/api/mqtt/workflows/{workflow_id}")
def get_mqtt_workflow(workflow_id: str) -> dict:
    record = mqtt_service.get_workflow(workflow_id)
    if record is None:
        raise HTTPException(status_code=404, detail="MQTT workflow was not found.")
    return record


@app.get("/api/mqtt/history")
def get_mqtt_history(
    workflow_id: str | None = Query(default=None, alias="workflowId"),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict:
    records = mqtt_service.query_history(workflow_id=workflow_id, limit=limit)
    return {
        "success": True,
        "workflowId": workflow_id,
        "count": len(records),
        "records": records,
    }


@app.get("/", include_in_schema=False)
def get_frontend_index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/data/{filename}", include_in_schema=False)
def get_public_data(filename: str) -> FileResponse:
    if filename not in PUBLIC_DATA_FILES:
        raise HTTPException(status_code=404, detail="Public data file was not found.")
    return FileResponse(FRONTEND_DIR / "data" / filename)


@app.get("/{filename}", include_in_schema=False)
def get_frontend_asset(filename: str) -> FileResponse:
    if filename not in PUBLIC_ASSETS:
        raise HTTPException(status_code=404, detail="Frontend asset was not found.")
    return FileResponse(FRONTEND_DIR / filename)
