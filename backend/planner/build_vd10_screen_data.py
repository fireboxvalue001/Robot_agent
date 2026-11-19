"""Maintain screen scenarios by referencing existing C2 skills, never creating skills."""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def write(path, data):
    (ROOT / path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build():
    library = json.loads((ROOT / "data/meta-operations.json").read_text(encoding="utf-8"))
    # Remove only the nine temporary interfaces introduced by this uncommitted experiment.
    temporary = {"robot.meta.vd10_screen_" + name for name in
        ("capture", "recognize", "click", "input_text", "select_option", "locate_touch", "approach_touch", "touch_once", "retract_touch")}
    library["meta_operations"] = [op for op in library["meta_operations"] if op["id"] not in temporary]
    library["schema_version"] = max(library["schema_version"], "1.8.2", key=lambda v: tuple(int(p) for p in v.split(".")))
    write("data/meta-operations.json", library)
    operations = {op["id"]: op for op in library["meta_operations"]}
    manual = json.loads((ROOT / "data/vd10_agent_only_operation_tree.json").read_text(encoding="utf-8"))
    controls = {node["capability_id"]: node["name"] for group in manual["capability_tree"] for node in group["capabilities"]}
    controls.update({node["node_ref"]: node["name"] for op in operations.values() for node in op["operation_tree"]["children"]})
    sample = {"sample_id": {"parameter_ref": "sample_id"}}
    read = ("robot.meta.read_result_from_screen", {"device_id": {"value": "vd10"}})
    scenes = [
        ("prepare", "测试信息填写", [("vd10.meta.prepare_test", {**sample, "operator": {"parameter_ref": "operator"}})]),
        ("query", "历史结果查询", [("vd10.meta.query_test_results", sample), read]),
        ("quality", "质量状态查看", [("vd10.meta.inspect_quality_status", {}), read]),
        ("robot_quality", "机械臂触屏质量状态查看", [
            ("robot.meta.operate_touchscreen", {"target_control": {"value": "vd10.menu.enter_quality"}, "expected_page": {"value": "quality_menu"}}),
            ("robot.meta.operate_touchscreen", {"target_control": {"value": "vd10.quality.open_status"}}), read])]
    patterns = {"prepare": ["VD10.*(?:屏幕|界面).*(?:填写|准备)"], "query": ["VD10.*(?:屏幕|界面).*(?:查询|检索)"],
        "quality": ["VD10.*(?:屏幕|界面).*(?:质量|质控)"], "robot_quality": ["(?:VD10.*机械臂|机械臂.*VD10).*触屏.*(?:质量|质控)"]}
    entries, targets, used = [], {}, set()
    for task, title, actions in scenes:
        params = {}
        if task in {"prepare", "query"}:
            params["sample_id"] = {"type": "string", "label": "样品编号", "anchors": ["样品编号"], "maxLength": 200}
        if task == "prepare":
            params["operator"] = {"type": "string", "label": "操作员", "anchors": ["操作员"], "maxLength": 200}
        nodes = [{"id": "start", "kind": "start", "label": "任务入口", "phase_id": "start", "requires": [], "next": "step_1"}]
        phases = [{"id": "start", "label": "任务入口"}]
        for i, (op_id, bindings) in enumerate(actions, 1):
            op = operations[op_id]
            used.add(op_id)
            target = bindings.get("target_control", {}).get("value")
            call_title = controls.get(target, op["name"])
            phases.append({"id": f"phase_{i}", "label": f"{i}. {call_title}"})
            nodes.append({"id": f"step_{i}", "kind": "action", "label": op["name"], "phase_id": f"phase_{i}",
                "requires": [b["parameter_ref"] for b in bindings.values() if "parameter_ref" in b],
                "operation_id": op_id, "input_bindings": bindings, "outputs": list(op["outputs"]["properties"]),
                "next": f"check_{i}", "on_error": "review", "on_timeout": "review",
                "display": {"title": call_title,
                    "fields": [{"argument": key, "label": {"target_control": "目标控件", "expected_page": "预期页面", "sample_id": "样品编号", "operator": "操作员", "device_id": "仪器"}.get(key, key)} for key in bindings],
                    "notice": "直接引用已有C2能力；多内部节点条目仍为历史组合，不是新定义的单步动作。"}})
            required = list(op["outputs"].get("required", []))
            nodes.append({"id": f"check_{i}", "kind": "guard", "label": "核验能力反馈", "phase_id": f"phase_{i}", "requires": [],
                "data_refs": [f"step_{i}.{field}" for field in required],
                "check": {"operation_id": op_id, "required_outputs": required,
                    **({"action_verified_equals": True} if "action_verified" in required else {})},
                "on_pass": f"step_{i+1}" if i < len(actions) else "complete", "on_fail": "review", "on_error": "review", "on_timeout": "review"})
            target = bindings.get("target_control", {}).get("value")
            if target:
                targets[target] = {"id": target, "source": "data/vd10_agent_only_operation_tree.json", "locator": None, "verified": False}
        nodes += [{"id": "complete", "kind": "end", "label": "流程结束 尚未执行", "phase_id": phases[-1]["id"], "requires": []},
                  {"id": "review", "kind": "end", "label": "停止任务并人工复核", "phase_id": "exception", "requires": []}]
        phases.append({"id": "exception", "label": "异常复核", "exception": True})
        scenario_id = "vd10_screen_" + task
        name = "VD10屏幕" + title if task != "robot_quality" else "VD10" + title
        write(f"knowledge/planner_scenarios/{scenario_id}.json", {"scenario_id": scenario_id, "name": name,
            "knowledge_id": "autolab.planner."+scenario_id, "version": "0.2.1", "review_status": "draft",
            "scope": name + "；只允许组合既有C2能力，不启动检测、不删除、不校准、不退出或关机。",
            "source": "data/meta-operations.json中的既有能力及原VD10说明书节点；不是新增硬件接口定义",
            "entry": "start", "resource_file": "data/vd10-screen-resources.json", "phases": phases, "parameters": params, "nodes": nodes,
            "blocked_request_patterns": [{"pattern": "(?<!不)(?<!不要)(?:启动|开始)(?:VD10)?(?:检测|测试)|(?<!不)(?<!不要)删除.*结果|(?<!不)(?<!不要)校准|(?<!不)(?<!不要)关机|(?<!不)(?<!不要)退出", "message": "该场景只支持已登记屏幕交互，不支持启动检测、删除、校准、退出或关机。"}],
            "limits": {"max_automatic_retries": 0, "execution_allowed": False}})
        entries.append({"id": scenario_id, "name": name, "engine": "conditional", "enabled": True,
            "file": f"knowledge/planner_scenarios/{scenario_id}.json", "routing_patterns": patterns[task],
            **({"routing_exclusions": ["机械臂.*触屏"]} if task == "quality" else {}), "ui": {"handoff_required": False, "parameter_mode": "process"}})
    write("data/vd10-screen-profile.json", {"contract_version": "1.0.0", "profile_id": "vd10.screen.profile.v1", "version": "0.2.0",
        "review_status": "draft", "execution_enabled": False, "adapter_implemented": False, "capability_ids": sorted(used), "targets": list(targets.values()),
        "notice": "仅保存既有说明书目标与定位占位，不定义能力。旧临时VD10专属接口已移除，历史档案保留快照但不得重新执行。"})
    write("data/vd10-screen-resources.json", {"resources": [{"id": "vd10.screen.binding", "name": "既有C2能力的设备与界面绑定", "type": "screen_adapter_profile",
        "implemented": False, "notice": "C2仍为草案或待验证；设备绑定、标定、控制及反馈需执行端确认，禁止执行。"}]})
    registry = json.loads((ROOT / "knowledge/planner_scenarios/registry.json").read_text(encoding="utf-8"))
    registry["scenarios"] = [e for e in registry["scenarios"] if e["id"] not in {v["id"] for v in entries}]
    next(e for e in registry["scenarios"] if e["id"] == "vd10_single_sample_demo")["routing_exclusions"] = [p for e in entries for p in e["routing_patterns"]]
    registry["scenarios"].extend(entries)
    write("knowledge/planner_scenarios/registry.json", registry)
    package = json.loads((ROOT / "PACKAGE_INFO.json").read_text(encoding="utf-8"))
    counts = Counter(op["category"] for op in library["meta_operations"])
    package["source_data"].update(total_meta_operations=len(operations), robot_meta_operations=counts["robot"], single_action_operations=sum(len(op["operation_tree"]["children"]) == 1 for op in operations.values()))
    write("PACKAGE_INFO.json", package)
    templates = json.loads((ROOT / "data/robot-action-templates.json").read_text(encoding="utf-8"))
    templates["library_version"] = library["schema_version"]
    write("data/robot-action-templates.json", templates)
    example = json.loads((ROOT / "examples/planner-result.sample.json").read_text(encoding="utf-8"))
    example["operationChain"]["capabilityLibrary"].update(version=library["schema_version"], checksum="sha256:" + hashlib.sha256((ROOT/"data/meta-operations.json").read_bytes()).hexdigest())
    write("examples/planner-result.sample.json", example)


if __name__ == "__main__":
    build()
