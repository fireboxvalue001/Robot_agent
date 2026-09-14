import os
import hashlib
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .asr_service import detect_voice_format, transcribe_with_tencent_cloud
from .mqtt_service import mqtt_service
from .planning_service import plan_natural_language


BACKEND_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")

MAX_AUDIO_SIZE = 3 * 1024 * 1024
META_OPERATION_LIBRARY = FRONTEND_DIR / "data" / "meta-operations.json"
SPATIAL_LOCATION_LIBRARY = FRONTEND_DIR / "data" / "spatial-locations.json"
PUBLIC_ASSETS = {
    "app.js", "index.html", "meta-operation.css", "mqtt-input.js",
    "styles.css", "voice-input.js",
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


class AsrTimingRequest(BaseModel):
    utteranceStartedAt: int = Field(ge=0)
    utteranceEndedAt: int = Field(ge=0)
    recognitionCompletedAt: int = Field(ge=0)
    audioDurationMs: int = Field(ge=0)
    timeUnit: str = Field(pattern="^unix_ms$")


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
        },
        "mqtt": mqtt_service.status(),
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
        },
        "timing": {
            "provider_elapsed_ms": result.elapsed_ms,
            "total_elapsed_ms": round((time.perf_counter() - started_at) * 1000),
        },
    }


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
