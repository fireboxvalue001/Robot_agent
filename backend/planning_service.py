import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent.parent
META_OPERATION_LIBRARY = PROJECT_DIR / "data" / "meta-operations.json"
DEFAULT_CHECKIN_LOCATION = "lab.location.sample_checkin_station"
DEFAULT_VD10_LOCATION = "lab.location.vd10_station"
DEFAULT_ELEVATOR_LINK = "lab.transport.elevator_floor1_to_floor3"
CHINESE_NUMBERS = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _load_library() -> tuple[dict[str, Any], dict[str, dict[str, Any]], str]:
    raw = META_OPERATION_LIBRARY.read_bytes()
    library = json.loads(raw.decode("utf-8"))
    operations = {operation["id"]: operation for operation in library["meta_operations"]}
    checksum = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    return library, operations, checksum


def _number(value: str) -> int:
    return int(value) if value.isdigit() else CHINESE_NUMBERS[value]


def _duration_seconds(text: str, prefix: str) -> int | None:
    match = re.search(
        rf"(?:{prefix})(?:时间为|持续|保持|约)?\s*(\d+(?:\.\d+)?)\s*(秒|分钟|小时)",
        text,
    )
    if not match:
        return None
    multiplier = {"秒": 1, "分钟": 60, "小时": 3600}[match.group(2)]
    return round(float(match.group(1)) * multiplier)


def _typed(value: Any, unit: str | None = None) -> dict[str, Any]:
    field = {"type": "number" if isinstance(value, (int, float)) else "string", "value": value}
    if unit:
        field["unit"] = unit
    return field


def parse_natural_language(text: str) -> dict[str, Any]:
    count_match = re.search(r"(\d+|一|二|两|三|四|五|六|七|八|九|十)\s*(?:份|个)(?!仪器)", text)
    if not count_match:
        count_match = re.search(r"分成\s*(\d+|一|二|两|三|四|五|六|七|八|九|十)", text)
    target_count = _number(count_match.group(1)) if count_match else 1

    volume_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:mL|ml|毫升)", text, re.IGNORECASE)
    volume_ml = float(volume_match.group(1)) if volume_match else None
    if volume_ml is not None and volume_ml.is_integer():
        volume_ml = int(volume_ml)

    floor_match = re.search(
        r"(?:送到|送至|搬到|运到|前往|到)\s*(\d+|一|二|两|三|四|五|六|七|八|九|十)\s*(?:楼|层)",
        text,
    )
    destination_floor = f"{_number(floor_match.group(1))}楼" if floor_match else None
    mentions_vd10 = bool(re.search(r"VD10", text, re.IGNORECASE))
    mentions_sample = bool(re.search(r"样品|试样|样本", text))
    mentions_split = bool(re.search(r"分成|分为|分装|等分", text))
    mentions_delivery = bool(re.search(r"送到|送至|送入|搬运|转运|放到|放入", text))
    mentions_result = bool(re.search(r"(?:查询|查看|读取|检索|获取).*(?:结果|报告|数据)", text))
    explicit_test_action = bool(re.search(
        r"(?:进行|执行|开展|完成|做|送到|送至|送入|用于).{0,30}(?:检测|测试|分析)|(?:检测|测试|分析)(?:样品|一下|并|然后|后|$)",
        text,
    ))
    mentions_test = bool(re.search(r"检测|测试|分析", text)) and (
        explicit_test_action or not mentions_result
    )
    mentions_heating = bool(re.search(r"加热|升温|恒温", text))
    mixing_match = re.search(r"摇匀|混匀|震荡|振荡", text)
    hold_match = re.search(r"静置", text)

    temperature_match = re.search(
        r"(?:温度(?:为|设为|设置为|到|至)?|加热(?:到|至))\s*(\d+(?:\.\d+)?)\s*(?:°C|℃|度|°)",
        text,
        re.IGNORECASE,
    )
    temperature_c = float(temperature_match.group(1)) if temperature_match else None
    if temperature_c is not None and temperature_c.is_integer():
        temperature_c = int(temperature_c)

    heating_duration = _duration_seconds(text, "加热|升温|恒温|持续|保持")
    mixing_duration = _duration_seconds(text, "摇匀|混匀|震荡|振荡")
    hold_duration = _duration_seconds(text, "静置")
    speed_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:rpm|转每分钟|转/分)", text, re.IGNORECASE)
    mixing_speed = float(speed_match.group(1)) if speed_match else None

    floor_after_test = bool(
        destination_floor
        and mentions_test
        and re.search(r"(?:最后|最终).*(?:楼|层)|(?:检测|测试|实验)(?:完成)?(?:后|之后|以后).*(?:楼|层)", text)
    )
    if mentions_vd10 and mentions_delivery and destination_floor is None:
        destination_floor = "3楼"

    parameters: dict[str, Any] = {"test_item_description": _typed(text)}
    if count_match:
        parameters["sample_count"] = _typed(target_count, "份")
    if volume_ml is not None:
        parameters["sample_volume_requirement"] = _typed(volume_ml, "mL")
    if destination_floor:
        parameters["destination_floor"] = _typed(destination_floor)
    if mentions_vd10:
        parameters["target_device"] = _typed("VD10")
    if temperature_c is not None:
        parameters["temperature_c"] = _typed(temperature_c, "°C")
    if mixing_match:
        parameters["mixing_requirement"] = _typed(mixing_match.group(0))
    elif hold_match:
        parameters["mixing_requirement"] = _typed("静置")
    if heating_duration:
        parameters["process_duration_seconds"] = _typed(heating_duration, "s")
    if mixing_duration:
        parameters["mixing_duration_seconds"] = _typed(mixing_duration, "s")
    if hold_duration:
        parameters["hold_duration_seconds"] = _typed(hold_duration, "s")
    if mixing_speed is not None:
        parameters["mixing_speed_rpm"] = _typed(mixing_speed, "rpm")

    missing: list[str] = []
    questions: list[str] = []
    if mentions_split and volume_ml is None:
        missing.append("sample_volume_requirement")
        questions.append("请补充每份样品的体积。")
    if mentions_heating and temperature_c is None:
        missing.append("temperature_c")
        questions.append("请补充样品加热的目标温度。")
    if hold_match and hold_duration is None:
        missing.append("hold_duration_seconds")
        questions.append("请补充样品静置时长。")

    return {
        "type": "local_preprocessing",
        "status": "success",
        "originalText": text,
        "parameters": parameters,
        "clarification": {
            "needed": bool(missing),
            "missingFields": missing,
            "questions": questions,
        },
        "facts": {
            "target_count": target_count,
            "volume_ml": volume_ml,
            "destination_floor": destination_floor,
            "mentions_vd10": mentions_vd10,
            "mentions_sample": mentions_sample,
            "mentions_split": mentions_split,
            "mentions_delivery": mentions_delivery,
            "mentions_test": mentions_test,
            "mentions_result": mentions_result,
            "mentions_heating": mentions_heating,
            "mixing_method": mixing_match.group(0) if mixing_match else None,
            "hold_requested": bool(hold_match),
            "temperature_c": temperature_c,
            "heating_duration": heating_duration,
            "mixing_duration": mixing_duration,
            "hold_duration": hold_duration,
            "mixing_speed": mixing_speed,
            "floor_after_test": floor_after_test,
        },
    }


def plan_natural_language(text: str, workflow_id: str | None = None) -> dict[str, Any]:
    clean_text = text.strip()
    workflow_id = workflow_id or f"wf_{uuid.uuid4()}"
    msg_id = f"msg_{uuid.uuid4()}"
    plan_id = f"plan_{uuid.uuid4()}"
    now = int(time.time() * 1000)
    preprocessing = parse_natural_language(clean_text)
    facts = preprocessing.pop("facts")
    preprocessing.update({"workflowId": workflow_id, "msgId": f"msg_{uuid.uuid4()}", "timestamp": now})
    library, operation_index, checksum = _load_library()
    selected: list[tuple[str, dict[str, Any]]] = []
    warnings: list[str] = []

    def select(operation_id: str, arguments: dict[str, Any] | None = None) -> None:
        if operation_id not in operation_index:
            raise ValueError(f"Capability is missing from the library: {operation_id}")
        selected.append((operation_id, arguments or {}))

    if preprocessing["clarification"]["needed"]:
        return _failed_result(
            msg_id, workflow_id, clean_text, preprocessing,
            preprocessing["clarification"]["questions"], now,
        )

    if facts["mentions_sample"] and facts["mentions_split"]:
        select("robot.meta.aliquot_sample", {
            "sample_id": "sample_pending_identification",
            "target_count": facts["target_count"],
            "volume_each": facts["volume_ml"],
            "source_location_id": DEFAULT_CHECKIN_LOCATION,
        })

    processing: list[tuple[int, str, dict[str, Any]]] = []
    if facts["mentions_heating"]:
        processing.append((clean_text.find("加热"), "robot.meta.heat_sample", {
            "sample_id": "sample_pending_identification",
            "heater_id": "heater_pending_binding",
            "temperature_c": facts["temperature_c"],
            "duration_seconds": facts["heating_duration"],
            "completion_condition": "duration_elapsed" if facts["heating_duration"] else "target_temperature_reached",
        }))
        warnings.append("加热设备仍需绑定，并核验容器耐温范围。")
    if facts["mixing_method"]:
        method = "vortex" if facts["mixing_method"] in {"震荡", "振荡"} else (
            "mix" if facts["mixing_method"] == "混匀" else "shake"
        )
        processing.append((clean_text.find(facts["mixing_method"]), "robot.meta.mix_sample", {
            "sample_id": "sample_pending_identification",
            "mixer_id": "mixer_pending_binding",
            "method": method,
            "speed_rpm": facts["mixing_speed"],
            "duration_seconds": facts["mixing_duration"],
            "completion_condition": "duration_elapsed" if facts["mixing_duration"] else "sensor_or_human_confirmation",
        }))
        warnings.append("混匀设备及未明确的运行参数需要在物理执行前确认。")
    if facts["hold_requested"]:
        processing.append((clean_text.find("静置"), "robot.meta.hold_sample", {
            "sample_id": "sample_pending_identification",
            "location_id": DEFAULT_CHECKIN_LOCATION,
            "duration_seconds": facts["hold_duration"],
        }))
    for _, operation_id, arguments in sorted(processing, key=lambda item: item[0]):
        select(operation_id, arguments)

    if facts["mentions_sample"] and facts["mentions_delivery"]:
        select("robot.meta.load_tube_to_agv", {
            "tube_ids": [f"tube_pending_{index + 1}" for index in range(facts["target_count"])],
            "agv_id": "agv_pending_binding",
        })

    if facts["destination_floor"] and not facts["floor_after_test"]:
        select("lab.meta.cross_zone_transport", {
            "source_zone": "floor_1_sample_checkin",
            "target_zone": f"floor_{facts['destination_floor'].replace('楼', '')}",
            "destination_floor": facts["destination_floor"],
            "transport_link_id": DEFAULT_ELEVATOR_LINK if facts["destination_floor"] == "3楼" else None,
        })

    if facts["mentions_sample"] and facts["mentions_delivery"]:
        select("lab.meta.transfer_sample_by_agv", {
            "source_station": DEFAULT_CHECKIN_LOCATION,
            "target_station": DEFAULT_VD10_LOCATION if facts["mentions_vd10"] else "instrument_pending_assignment",
            "sample_count": facts["target_count"],
        })
        select("robot.meta.prepare_and_load_instrument", {
            "sample_id": "sample_pending_identification",
            "target_device": "vd10" if facts["mentions_vd10"] else "instrument_pending_assignment",
        })

    if facts["mentions_test"]:
        select("vd10.meta.sample_test", {
            "sample_id": "sample_pending_identification",
            "sample_volume": facts["volume_ml"],
            "target_device": "vd10" if facts["mentions_vd10"] else "instrument_pending_assignment",
        })
        if not facts["mentions_vd10"]:
            warnings.append("未指定具体检测仪器，当前按VD10演示能力生成，执行前必须完成仪器绑定。")
        select("vd10.meta.query_test_results", {"sample_id": "sample_pending_identification"})
        select("robot.meta.read_result_from_screen", {"device_id": "vd10" if facts["mentions_vd10"] else "instrument_pending_assignment"})
    elif facts["mentions_result"]:
        select("vd10.meta.query_test_results", {"sample_id": "sample_pending_identification"})
        select("robot.meta.read_result_from_screen", {"device_id": "vd10" if facts["mentions_vd10"] else "instrument_pending_assignment"})

    if facts["destination_floor"] and facts["floor_after_test"]:
        select("lab.meta.cross_zone_transport", {
            "source_zone": "instrument_zone",
            "target_zone": f"floor_{facts['destination_floor'].replace('楼', '')}",
            "destination_floor": facts["destination_floor"],
            "transport_link_id": DEFAULT_ELEVATOR_LINK if facts["destination_floor"] == "3楼" else None,
        })

    if not selected:
        return _failed_result(
            msg_id, workflow_id, clean_text, preprocessing,
            ["自然语言未匹配到当前元操作能力库中的可编排任务。"], now,
        )

    operations: list[dict[str, Any]] = []
    readable_steps: list[dict[str, Any]] = []
    previous_step: str | None = None
    for sequence, (operation_id, arguments) in enumerate(selected, start=1):
        operation = operation_index[operation_id]
        step_id = f"step_{sequence:03d}"
        operations.append({
            "stepId": step_id,
            "sequence": sequence,
            "metaOperationId": operation_id,
            "metaOperationVersion": operation["version"],
            "arguments": arguments,
            "dependsOn": [previous_step] if previous_step else [],
        })
        readable_steps.append({"step": sequence, "action": operation["name"]})
        previous_step = step_id

    warnings.append("该结果用于编排模拟，标记为草案或接口预留的能力仍需物理可执行确认。")
    return {
        "msgId": msg_id,
        "type": "planner_result",
        "author": "vd10_local_text_planner",
        "workflowId": workflow_id,
        "index": 2,
        "status": "success",
        "history": [],
        "experimentName": "VD10自然语言实验编排",
        "steps": readable_steps,
        "parameters": preprocessing["parameters"],
        "operationChain": {
            "contractVersion": "1.0.0",
            "planId": plan_id,
            "capabilityLibrary": {
                "id": library["library_id"],
                "version": library["schema_version"],
                "checksum": checksum,
            },
            "operations": operations,
        },
        "warnings": list(dict.fromkeys(warnings)),
        "preprocessing": preprocessing,
        "timestamp": now,
    }


def _failed_result(
    msg_id: str,
    workflow_id: str,
    text: str,
    preprocessing: dict[str, Any],
    warnings: list[str],
    timestamp: int,
) -> dict[str, Any]:
    return {
        "msgId": msg_id,
        "type": "planner_result",
        "author": "vd10_local_text_planner",
        "workflowId": workflow_id,
        "index": 2,
        "status": "failed",
        "history": [],
        "experimentName": "自然语言任务未完成编排",
        "steps": [],
        "parameters": preprocessing["parameters"],
        "warnings": warnings,
        "preprocessing": preprocessing,
        "originalText": text,
        "timestamp": timestamp,
    }
