import copy
import hashlib
import json
import os
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import paho.mqtt.client as mqtt
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent / ".env")


TOPIC_UI_INPUT = "autolab/ui/input"
TOPIC_SEMANTIC_PARAMS = "autolab/semantic/params"
TOPIC_PLANNER_RESULT = "autolab/planner/result"
TOPIC_PHYSICAL_VALIDATION = "autolab/physical/validation"
VALID_STATUSES = {"processing", "success", "failed"}
MAX_WORKFLOWS = 200
MAX_SEEN_MESSAGES = 1000
DEFAULT_HISTORY_DIR = Path(__file__).resolve().parent.parent / "data" / "mqtt_history"
META_OPERATION_LIBRARY = Path(__file__).resolve().parent.parent / "data" / "meta-operations.json"


def get_capability_identity() -> dict[str, str]:
    raw = META_OPERATION_LIBRARY.read_bytes()
    library = json.loads(raw.decode("utf-8"))
    return {
        "id": library["library_id"],
        "version": library["schema_version"],
        "checksum": f"sha256:{hashlib.sha256(raw).hexdigest()}",
    }


class MqttHistoryStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._lock = threading.Lock()

    def append(self, record: dict[str, Any]) -> None:
        now = datetime.now().astimezone()
        entry = {
            "recorded_at": now.isoformat(timespec="milliseconds"),
            "recorded_timestamp": int(now.timestamp() * 1000),
            **record,
        }
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f"{now.date().isoformat()}.jsonl"
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line + "\n")

    def query(self, workflow_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if not self.directory.exists():
            return records
        with self._lock:
            for path in sorted(self.directory.glob("*.jsonl"), reverse=True):
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                for line in reversed(lines):
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if workflow_id and record.get("workflowId") != workflow_id:
                        continue
                    records.append(record)
                    if len(records) >= limit:
                        return records
        return records


class MqttService:
    def __init__(self) -> None:
        self.host = os.getenv("MQTT_HOST", "cangqiong.sjtusc.cn")
        self.port = int(os.getenv("MQTT_PORT", "1883"))
        self.keepalive = int(os.getenv("MQTT_KEEPALIVE", "60"))
        self.qos = int(os.getenv("MQTT_QOS", "0"))
        self.enabled = os.getenv("MQTT_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
        self.author = os.getenv("MQTT_UI_AUTHOR", "vd10_ui")
        self._connected = threading.Event()
        self._lock = threading.RLock()
        self._workflows: dict[str, dict[str, Any]] = {}
        self._workflow_order: deque[str] = deque()
        self._seen_ids: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._last_error: str | None = None
        self._history_error: str | None = None
        configured_history_dir = os.getenv("MQTT_HISTORY_DIR", "").strip()
        history_dir = Path(configured_history_dir) if configured_history_dir else DEFAULT_HISTORY_DIR
        self.history = MqttHistoryStore(history_dir)
        self._client = self._create_client()

    def _create_client(self) -> mqtt.Client:
        client_id = f"vd10-ui-{uuid.uuid4().hex[:12]}"
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=True,
        )
        username = os.getenv("MQTT_USERNAME")
        if username:
            client.username_pw_set(username, os.getenv("MQTT_PASSWORD"))
        if os.getenv("MQTT_TLS", "false").lower() in {"1", "true", "yes", "on"}:
            client.tls_set()
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        return client

    def start(self) -> None:
        if not self.enabled:
            return
        try:
            self._client.connect_async(self.host, self.port, self.keepalive)
            self._client.loop_start()
        except Exception as exc:
            self._last_error = str(exc)

    def stop(self) -> None:
        if not self.enabled:
            return
        try:
            self._client.disconnect()
        finally:
            self._client.loop_stop()
            self._connected.clear()

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "connected": self._connected.is_set(),
            "host": self.host,
            "port": self.port,
            "topics": {
                "publish": TOPIC_UI_INPUT,
                "subscribe": [
                    TOPIC_SEMANTIC_PARAMS,
                    TOPIC_PLANNER_RESULT,
                    TOPIC_PHYSICAL_VALIDATION,
                ],
            },
            "last_error": self._last_error,
            "history": {
                "enabled": True,
                "error": self._history_error,
            },
        }

    def publish_ui_input(
        self,
        text: str,
        asr_timing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Input text must not be empty.")
        if not self.enabled:
            raise ConnectionError("MQTT is disabled.")
        if not self._connected.is_set():
            raise ConnectionError("MQTT broker is not connected.")
        if asr_timing is not None:
            validate_asr_timing(asr_timing)

        workflow_id = f"wf_{uuid.uuid4()}"
        message = {
            "msgId": f"msg_{uuid.uuid4()}",
            "type": "ui_input",
            "author": self.author,
            "workflowId": workflow_id,
            "index": 0,
            "status": "processing",
            "history": [],
            "text": clean_text,
            "timestamp": int(time.time() * 1000),
        }
        if asr_timing is not None:
            message["asrTiming"] = copy.deepcopy(asr_timing)
        record = {
            "workflowId": workflow_id,
            "state": "waiting_semantic_params",
            "ui_input": message,
            "semantic_params": None,
            "planner_result": None,
            "physical_validation": None,
            "error": None,
            "updated_at": message["timestamp"],
        }
        with self._lock:
            self._store_workflow(workflow_id, record)

        payload = json.dumps(message, ensure_ascii=False)
        info = self._client.publish(TOPIC_UI_INPUT, payload, qos=self.qos, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            with self._lock:
                record["state"] = "publish_failed"
                record["error"] = f"MQTT publish failed with code {info.rc}."
            self._record_history(
                event="ui_input_publish_failed",
                direction="outbound",
                topic=TOPIC_UI_INPUT,
                payload=message,
                error=record["error"],
            )
            raise ConnectionError(record["error"])
        self._record_history(
            event="ui_input_published",
            direction="outbound",
            topic=TOPIC_UI_INPUT,
            payload=message,
        )
        return copy.deepcopy(record)

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._workflows.get(workflow_id)
            return copy.deepcopy(record) if record else None

    def query_history(self, workflow_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self.history.query(workflow_id=workflow_id, limit=limit)

    def accept_semantic_message(self, payload: Any) -> tuple[bool, str | None]:
        error = validate_semantic_message(payload)
        if error:
            self._record_history(
                event="semantic_params_rejected",
                direction="inbound",
                topic=TOPIC_SEMANTIC_PARAMS,
                payload=payload,
                error=error,
            )
            return False, error

        msg_id = payload["msgId"]
        workflow_id = payload["workflowId"]
        with self._lock:
            if msg_id in self._seen_ids:
                self._record_history(
                    event="semantic_params_duplicate_ignored",
                    direction="inbound",
                    topic=TOPIC_SEMANTIC_PARAMS,
                    payload=payload,
                    error="duplicate_msg_id",
                )
                return False, "duplicate_msg_id"
            self._remember_message(msg_id)
            record = self._workflows.get(workflow_id)
            if record is None:
                record = {
                    "workflowId": workflow_id,
                    "state": "semantic_received_without_local_request",
                    "ui_input": None,
                    "semantic_params": None,
                    "planner_result": None,
                    "physical_validation": None,
                    "error": None,
                    "updated_at": payload["timestamp"],
                }
                self._store_workflow(workflow_id, record)
            record["semantic_params"] = copy.deepcopy(payload)
            record["state"] = "semantic_failed" if payload["status"] == "failed" else "semantic_received"
            record["updated_at"] = payload["timestamp"]
        self._record_history(
            event="semantic_params_received",
            direction="inbound",
            topic=TOPIC_SEMANTIC_PARAMS,
            payload=payload,
        )
        return True, None

    def accept_planner_message(self, payload: Any) -> tuple[bool, str | None]:
        error = validate_planner_message(payload)
        if not error and payload["status"] == "success":
            expected = get_capability_identity()
            received = payload["operationChain"]["capabilityLibrary"]
            if any(received.get(key) != expected[key] for key in ("id", "version", "checksum")):
                error = "capability_library_mismatch"
        if error:
            self._record_history("planner_result_rejected", "inbound", TOPIC_PLANNER_RESULT, payload, error)
            return False, error
        return self._accept_workflow_result(
            payload, "planner_result", "planner_received", "planner_failed", TOPIC_PLANNER_RESULT
        )

    def accept_physical_validation(self, payload: Any) -> tuple[bool, str | None]:
        error = validate_physical_validation(payload)
        if not error:
            with self._lock:
                planner = self._workflows.get(payload["workflowId"], {}).get("planner_result")
            expected_plan_id = planner.get("operationChain", {}).get("planId") if planner else None
            if expected_plan_id and payload["planId"] != expected_plan_id:
                error = "plan_id_mismatch"
        if error:
            self._record_history("physical_validation_rejected", "inbound", TOPIC_PHYSICAL_VALIDATION, payload, error)
            return False, error
        return self._accept_workflow_result(
            payload, "physical_validation", "physical_validation_received",
            "physical_validation_failed", TOPIC_PHYSICAL_VALIDATION
        )

    def _accept_workflow_result(
        self,
        payload: dict[str, Any],
        field: str,
        success_state: str,
        failed_state: str,
        topic: str,
    ) -> tuple[bool, str | None]:
        msg_id = payload["msgId"]
        workflow_id = payload["workflowId"]
        with self._lock:
            if msg_id in self._seen_ids:
                self._record_history(f"{field}_duplicate_ignored", "inbound", topic, payload, "duplicate_msg_id")
                return False, "duplicate_msg_id"
            self._remember_message(msg_id)
            record = self._workflows.get(workflow_id)
            if record is None:
                record = {
                    "workflowId": workflow_id,
                    "state": f"{field}_received_without_local_request",
                    "ui_input": None,
                    "semantic_params": None,
                    "planner_result": None,
                    "physical_validation": None,
                    "error": None,
                    "updated_at": payload["timestamp"],
                }
                self._store_workflow(workflow_id, record)
            record[field] = copy.deepcopy(payload)
            record["state"] = failed_state if payload["status"] == "failed" else success_state
            record["updated_at"] = payload["timestamp"]
        self._record_history(f"{field}_received", "inbound", topic, payload)
        return True, None

    def _record_history(
        self,
        event: str,
        direction: str,
        topic: str,
        payload: Any,
        error: str | None = None,
    ) -> None:
        workflow_id = payload.get("workflowId") if isinstance(payload, dict) else None
        msg_id = payload.get("msgId") if isinstance(payload, dict) else None
        try:
            self.history.append({
                "event": event,
                "direction": direction,
                "topic": topic,
                "workflowId": workflow_id,
                "msgId": msg_id,
                "payload": copy.deepcopy(payload),
                "error": error,
            })
            self._history_error = None
        except (OSError, TypeError, ValueError) as exc:
            self._history_error = str(exc)

    def _store_workflow(self, workflow_id: str, record: dict[str, Any]) -> None:
        if workflow_id not in self._workflows:
            self._workflow_order.append(workflow_id)
        self._workflows[workflow_id] = record
        while len(self._workflow_order) > MAX_WORKFLOWS:
            old_id = self._workflow_order.popleft()
            self._workflows.pop(old_id, None)

    def _remember_message(self, msg_id: str) -> None:
        self._seen_ids.add(msg_id)
        self._seen_order.append(msg_id)
        while len(self._seen_order) > MAX_SEEN_MESSAGES:
            self._seen_ids.discard(self._seen_order.popleft())

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code == 0:
            self._connected.set()
            self._last_error = None
            client.subscribe([
                (TOPIC_SEMANTIC_PARAMS, self.qos),
                (TOPIC_PLANNER_RESULT, self.qos),
                (TOPIC_PHYSICAL_VALIDATION, self.qos),
            ])
        else:
            self._connected.clear()
            self._last_error = f"MQTT connection failed with reason code {reason_code}."

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None) -> None:
        self._connected.clear()
        if reason_code != 0:
            self._last_error = f"MQTT disconnected with reason code {reason_code}."

    def _on_message(self, client, userdata, message) -> None:
        validators = {
            TOPIC_SEMANTIC_PARAMS: self.accept_semantic_message,
            TOPIC_PLANNER_RESULT: self.accept_planner_message,
            TOPIC_PHYSICAL_VALIDATION: self.accept_physical_validation,
        }
        accept = validators.get(message.topic)
        if accept is None:
            return
        try:
            payload = json.loads(message.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._last_error = f"Invalid MQTT message JSON: {exc}"
            self._record_history(
                event="mqtt_message_invalid_json",
                direction="inbound",
                topic=TOPIC_SEMANTIC_PARAMS,
                payload=message.payload.decode("utf-8", errors="replace"),
                error=str(exc),
            )
            return
        accepted, error = accept(payload)
        if not accepted and error != "duplicate_msg_id":
            self._last_error = f"Invalid MQTT message on {message.topic}: {error}"


def validate_asr_timing(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("asrTiming must be an object.")
    required = {
        "utteranceStartedAt",
        "utteranceEndedAt",
        "recognitionCompletedAt",
        "audioDurationMs",
        "timeUnit",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise ValueError(f"asrTiming is missing fields: {','.join(missing)}")
    for field in (
        "utteranceStartedAt",
        "utteranceEndedAt",
        "recognitionCompletedAt",
        "audioDurationMs",
    ):
        value = payload[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"asrTiming.{field} must be a non-negative integer.")
    if payload["timeUnit"] != "unix_ms":
        raise ValueError("asrTiming.timeUnit must be unix_ms.")
    if payload["utteranceEndedAt"] < payload["utteranceStartedAt"]:
        raise ValueError("asrTiming utterance end must not precede its start.")
    if payload["recognitionCompletedAt"] < payload["utteranceEndedAt"]:
        raise ValueError("asrTiming recognition completion must not precede utterance end.")
    expected_duration = payload["utteranceEndedAt"] - payload["utteranceStartedAt"]
    if payload["audioDurationMs"] != expected_duration:
        raise ValueError("asrTiming.audioDurationMs must equal utterance end minus start.")


def validate_semantic_message(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return "payload_must_be_object"
    required = {
        "msgId", "type", "author", "workflowId", "index", "status", "history",
        "originalText", "parameters", "timestamp"
    }
    missing = sorted(required.difference(payload))
    if missing:
        return f"missing_fields:{','.join(missing)}"
    if payload["type"] != "semantic_params":
        return "invalid_type"
    if payload["status"] not in VALID_STATUSES:
        return "invalid_status"
    if not isinstance(payload["msgId"], str) or not payload["msgId"].startswith("msg_"):
        return "invalid_msg_id"
    if not isinstance(payload["workflowId"], str) or not payload["workflowId"].startswith("wf_"):
        return "invalid_workflow_id"
    if not isinstance(payload["index"], int):
        return "invalid_index"
    if not isinstance(payload["history"], list):
        return "invalid_history"
    if not isinstance(payload["originalText"], str):
        return "invalid_original_text"
    if not isinstance(payload["parameters"], dict):
        return "invalid_parameters"
    if not isinstance(payload["timestamp"], (int, float)):
        return "invalid_timestamp"
    return None


def _validate_common_message(payload: Any, expected_type: str) -> str | None:
    if not isinstance(payload, dict):
        return "payload_must_be_object"
    required = {"msgId", "type", "author", "workflowId", "index", "status", "history", "timestamp"}
    missing = sorted(required.difference(payload))
    if missing:
        return f"missing_fields:{','.join(missing)}"
    if payload["type"] != expected_type:
        return "invalid_type"
    if payload["status"] not in VALID_STATUSES:
        return "invalid_status"
    if not isinstance(payload["msgId"], str) or not payload["msgId"].startswith("msg_"):
        return "invalid_msg_id"
    if not isinstance(payload["workflowId"], str) or not payload["workflowId"].startswith("wf_"):
        return "invalid_workflow_id"
    if not isinstance(payload["index"], int) or isinstance(payload["index"], bool):
        return "invalid_index"
    if not isinstance(payload["history"], list):
        return "invalid_history"
    if not isinstance(payload["timestamp"], (int, float)) or isinstance(payload["timestamp"], bool):
        return "invalid_timestamp"
    return None


def validate_planner_message(payload: Any) -> str | None:
    error = _validate_common_message(payload, "planner_result")
    if error:
        return error
    required = {"experimentName", "steps", "parameters"}
    missing = sorted(required.difference(payload))
    if missing:
        return f"missing_fields:{','.join(missing)}"
    if not isinstance(payload["experimentName"], str):
        return "invalid_experiment_name"
    if not isinstance(payload["steps"], list) or not isinstance(payload["parameters"], dict):
        return "invalid_planner_payload"
    if payload["status"] == "success":
        chain = payload.get("operationChain")
        if not isinstance(chain, dict):
            return "missing_operation_chain"
        chain_required = {"contractVersion", "planId", "capabilityLibrary", "operations"}
        missing = sorted(chain_required.difference(chain))
        if missing:
            return f"missing_operation_chain_fields:{','.join(missing)}"
        if not isinstance(chain["planId"], str) or not chain["planId"].startswith("plan_"):
            return "invalid_plan_id"
        if not isinstance(chain["capabilityLibrary"], dict) or not isinstance(chain["operations"], list):
            return "invalid_operation_chain"
        seen_steps: set[str] = set()
        for operation in chain["operations"]:
            if not isinstance(operation, dict):
                return "invalid_operation"
            operation_required = {
                "stepId", "sequence", "metaOperationId", "metaOperationVersion", "arguments", "dependsOn"
            }
            if operation_required.difference(operation):
                return "incomplete_operation"
            if not isinstance(operation["stepId"], str) or operation["stepId"] in seen_steps:
                return "invalid_or_duplicate_step_id"
            seen_steps.add(operation["stepId"])
            if not isinstance(operation["sequence"], int) or isinstance(operation["sequence"], bool):
                return "invalid_operation_sequence"
            if not isinstance(operation["metaOperationId"], str) or not isinstance(operation["metaOperationVersion"], str):
                return "invalid_meta_operation_reference"
            if not isinstance(operation["arguments"], dict) or not isinstance(operation["dependsOn"], list):
                return "invalid_operation_bindings"
        if any(dependency not in seen_steps for operation in chain["operations"] for dependency in operation["dependsOn"]):
            return "unknown_step_dependency"
    return None


def validate_physical_validation(payload: Any) -> str | None:
    error = _validate_common_message(payload, "physical_validation")
    if error:
        return error
    required = {"planId", "result", "stepResults"}
    missing = sorted(required.difference(payload))
    if missing:
        return f"missing_fields:{','.join(missing)}"
    if not isinstance(payload["planId"], str) or not payload["planId"].startswith("plan_"):
        return "invalid_plan_id"
    if payload["result"] not in {"executable", "blocked", "requires_confirmation"}:
        return "invalid_physical_result"
    if not isinstance(payload["stepResults"], list):
        return "invalid_step_results"
    for result in payload["stepResults"]:
        if not isinstance(result, dict) or not {"stepId", "executable", "checks", "blockers"}.issubset(result):
            return "invalid_step_result"
        if not isinstance(result["executable"], bool) or not isinstance(result["checks"], list) or not isinstance(result["blockers"], list):
            return "invalid_step_result_fields"
    return None


mqtt_service = MqttService()
