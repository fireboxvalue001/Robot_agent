"""Resolve local semantic JSON into precise text without selecting capabilities."""

import copy
import math
import re
import time
import uuid
from typing import Any

def resolve_local_semantic(payload: dict[str, Any]) -> dict[str, Any]:
    workflow_id = payload.get("workflowId") or f"wf_{uuid.uuid4()}"
    if not isinstance(workflow_id, str) or not workflow_id.startswith("wf_"):
        raise ValueError("workflowId must start with wf_.")
    original_text = payload.get("originalText")
    errors: dict[str, str] = {}
    if not isinstance(original_text, str) or not original_text.strip() or len(original_text) > 10000:
        errors["originalText"] = "请提供有效的原始任务文字（最多10000字符）。"
        original_text = ""
    if payload.get("type") != "semantic_params":
        errors["type"] = "本地输入类型应为 semantic_params。"
    if payload.get("status", "success") != "success":
        errors["status"] = "意图解析尚未成功，请先完成解析。"
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict):
        errors["parameters"] = "请提供对象形式的解析参数。"
        parameters = {}
    if parameters.get("intent") != "add_to":
        errors["intent"] = "当前本地适配仅支持容器间定量移液 add_to。"
    unresolved = parameters.get("unresolved", [])
    if not isinstance(unresolved, list) or unresolved:
        errors["unresolved"] = "解析结果仍存在未明确的信息，请先完成确认。"
    operations = parameters.get("operations")
    if not isinstance(operations, list) or len(operations) != 1 or not isinstance(operations[0], dict):
        errors["operations"] = "当前场景需要且仅支持一个 add 操作。"
        parsed_operation = {}
    else:
        parsed_operation = operations[0]
    if parsed_operation.get("action") != "add":
        errors["action"] = "当前场景只支持 add 液体加入操作。"
    arguments = parsed_operation.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    bound: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for field, prefix in [("sourceObject", "source"), ("targetObject", "target")]:
        obj = arguments.get(field)
        object_id = obj.get("objectId") if isinstance(obj, dict) else None
        if not isinstance(object_id, str) or not object_id.strip():
            errors[field] = f"请确认{'来源' if prefix == 'source' else '目标'}容器的 objectId。"
            continue
        bound[f"{prefix}_object_id"] = object_id.strip()
        name = obj.get("objectName")
        bound[f"{prefix}_object_name"] = name.strip() if isinstance(name, str) and name.strip() else object_id.strip()
        sources[f"{prefix}_object_id"] = f"parameters.operations[0].arguments.{field}.objectId"
        sources[f"{prefix}_object_name"] = f"parameters.operations[0].arguments.{field}.{'objectName' if isinstance(name, str) and name.strip() else 'objectId'}"
    if bound.get("source_object_id") and bound.get("source_object_id") == bound.get("target_object_id"):
        errors["targetObject"] = "来源与目标不能是同一个容器。"

    # Only recover a quantity from the original text when it states one amount.
    amounts = re.findall(r"(?<![A-Za-z0-9_.])[-+−]?\d+(?:\.\d+)?\s*(?:ml|毫升)(?![A-Za-z])", original_text, re.I)
    text_volume = float(re.match(r"[-+]?\d+(?:\.\d+)?", amounts[0].replace("−", "-")).group()) if len(amounts) == 1 else None
    if "volume" in arguments:
        volume = arguments["volume"]
        value = volume.get("value") if isinstance(volume, dict) else None
        unit = volume.get("unit") if isinstance(volume, dict) else None
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or
                not math.isfinite(value) or value <= 0 or not isinstance(unit, str) or unit.lower() not in {"ml", "毫升"}):
            errors["volume"] = "volume 需要大于0的数值及 mL 单位。"
        elif len(amounts) > 1:
            errors["volume"] = "原文有多个体积，请明确本次移液体积。"
        elif text_volume is not None and not math.isclose(value, text_volume, rel_tol=1e-9):
            errors["volume"] = "解析体积与原文不一致，请核对后重新提交。"
        else:
            bound["volume_ml"] = value
            sources["volume_ml"] = "parameters.operations[0].arguments.volume"
    elif text_volume is not None and math.isfinite(text_volume) and text_volume > 0:
        bound["volume_ml"] = text_volume
        sources["volume_ml"] = "originalText"
    else:
        errors["volume"] = "请明确一个大于0的移液体积，例如10mL。"

    for key in ("source_object_id", "target_object_id"):
        if key in bound and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", bound[key]):
            errors[key] = "容器编号需为不超过100字符的字母、数字或 _ . : -。"
    for key in ("source_object_name", "target_object_name"):
        if key in bound and (len(bound[key]) > 100 or re.search(r"[（）\r\n]", bound[key])):
            errors[key] = "容器名称需不超过100字符，且不包含换行或全角括号。"
    success = not errors
    normalized = {
        "operation_description": {"type": "string", "value": "容器间定量移液"},
        **{key: {"type": "number" if key == "volume_ml" else "string", "value": value,
                 **({"unit": "mL"} if key == "volume_ml" else {})} for key, value in bound.items()},
    }
    amount_display = f"{bound['volume_ml']:g}" if "volume_ml" in bound else "待确认"
    description = f"从{bound.get('source_object_name', '来源容器')}（容器编号：{bound.get('source_object_id', '待确认')}）中吸取{amount_display}mL液体，加入{bound.get('target_object_name', '目标容器')}（容器编号：{bound.get('target_object_id', '待确认')}）中。"
    normalized["operation_description"]["value"] = description
    now = int(time.time() * 1000)
    preprocessing = {
        "type": "local_preprocessing", "status": "success" if success else "failed",
        "workflowId": workflow_id, "originalText": description if success else original_text, "parameters": normalized,
        "clarification": {"needed": not success, "missingFields": list(errors), "questions": list(errors.values())},
    }
    result = {
        "msgId": f"msg_{uuid.uuid4()}", "type": "resolved_intent", "author": "vd10_local_semantic_adapter",
        "workflowId": workflow_id, "status": "success" if success else "failed",
        "originalText": original_text, "resolvedText": description if success else None,
        "warnings": list(errors.values()), "preprocessing": preprocessing, "timestamp": now,
        "sourceSemantic": copy.deepcopy(payload),
        "adapterMetadata": {"sourceOperationId": parsed_operation.get("operationId"), "parameterSources": sources},
        "execution_allowed": False, "physical_status": "not_evaluated",
    }
    return result


# Compatibility name for local callers; the return value is now resolved_intent.
plan_local_semantic = resolve_local_semantic
