"""Maintain the document-derived scenario and append its single-action interfaces."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def write(path, value):
    (ROOT / path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build():
    library = json.loads((ROOT / "data/meta-operations.json").read_text(encoding="utf-8"))
    instruments = {"balance": "分析天平", "drying_oven": "烘箱", "water_bath": "水浴设备",
                   "condenser": "冷凝水装置", "solvent_remover": "溶剂去除设备（待确定方法）"}
    for key, name in instruments.items():
        if key not in {item["id"] for item in library["instruments"]}:
            library["instruments"].append({"id": key, "name": name, "status": "interface_only"})
    actions = [
        ("robot.meta.cut_leather", "皮革单次剪切", None, ["sample_id", "tool_id", "cut_path_id"], ["cut_completed"]),
        ("robot.meta.insert_extraction_sample", "滤纸筒装入皮革样品", None, ["sample_id", "thimble_id"], ["sample_loaded"]),
        ("robot.meta.place_cotton", "放置脱脂棉", None, ["cotton_id", "thimble_id", "placement_id"], ["cotton_placed"]),
        ("robot.meta.connect_glass_joint", "连接玻璃接口", None, ["source_joint_id", "target_joint_id"], ["joint_connected"]),
        ("robot.meta.disconnect_glass_joint", "分离玻璃接口", None, ["source_joint_id", "target_joint_id"], ["joint_disconnected"]),
        ("robot.meta.fasten_clamp", "固定夹具", None, ["clamp_id", "object_id"], ["clamp_fastened"]),
        ("robot.meta.release_clamp", "松开夹具", None, ["clamp_id", "object_id"], ["clamp_released"]),
        ("robot.meta.inspect_extraction_assembly", "检查抽提装置连接", None, ["assembly_id"], ["assembly_ready"]),
        ("robot.meta.read_balance_mass", "读取天平质量", None, ["device_id", "object_id"], ["mass_g", "stable"]),
        ("robot.meta.monitor_reflux", "检查冷凝回流与虹吸状态", None, ["assembly_id", "monitor_profile_id"], ["reflux_ok", "siphon_ok", "condensation_ok", "completed_cycles"]),
        ("robot.meta.check_temperature", "读取对象温度", None, ["object_id", "sensor_id"], ["temperature_c"]),
        ("robot.meta.check_solvent_residue", "检查溶剂残留状态", None, ["object_id", "method_id"], ["residue_check_passed"]),
        ("robot.meta.rinse_vessel", "执行容器清洗动作", None, ["object_id", "cleaning_profile_id"], ["rinsing_completed"]),
        ("robot.meta.open_device_door", "打开设备门", None, ["device_id"], ["door_open"]),
        ("robot.meta.close_device_door", "关闭设备门", None, ["device_id"], ["door_closed"]),
        ("robot.meta.transfer_solid_piece", "放置一块皮革样品", None, ["sample_id", "target_object_id"], ["piece_placed"]),
        ("balance.meta.tare", "天平去皮", "balance", ["device_id"], ["tare_completed"]),
        ("drying_oven.meta.set_temperature", "设置烘箱温度", "drying_oven", ["device_id", "temperature_c"], ["temperature_set"]),
        ("drying_oven.meta.start", "启动烘箱", "drying_oven", ["device_id"], ["running"]),
        ("drying_oven.meta.stop", "停止烘箱加热", "drying_oven", ["device_id"], ["stopped"]),
        ("water_bath.meta.set_temperature", "设置水浴温度", "water_bath", ["device_id", "temperature_c"], ["temperature_set"]),
        ("water_bath.meta.start", "启动水浴加热", "water_bath", ["device_id"], ["running"]),
        ("water_bath.meta.stop", "停止水浴加热", "water_bath", ["device_id"], ["stopped"]),
        ("condenser.meta.open_water", "开启冷凝水", "condenser", ["device_id"], ["water_enabled"]),
        ("condenser.meta.close_water", "关闭冷凝水", "condenser", ["device_id"], ["water_disabled"]),
        ("condenser.meta.read_flow", "读取冷凝水流量", "condenser", ["device_id"], ["flow_rate"]),
        ("solvent_remover.meta.start", "启动已登记溶剂去除程序", "solvent_remover", ["device_id", "method_id"], ["started"]),
        ("solvent_remover.meta.stop", "停止溶剂去除程序", "solvent_remover", ["device_id"], ["stopped"]),
        ("lab.meta.verify_ventilation", "核验通风状态", None, ["station_id"], ["ventilation_ok"]),
    ]
    for op_id, name, instrument, fields, outputs in actions:
        if op_id in {o["id"] for o in library["meta_operations"]}:
            continue
        properties = {field: {"type": "number"} if field == "temperature_c" else {"type": "string", "minLength": 1} for field in fields}
        properties["control_profile_id"] = {"type": "string", "minLength": 1}
        op = {
            "id": op_id, "version": "1.0.0", "name": name,
            "category": "instrument" if instrument else "lab" if op_id.startswith("lab.") else "robot",
            "description": f"仅执行{name}这一项动作；定位、搬运、等待和结果判定由流程分别编排。",
            "status": "interface_only", "execution_policy": "interface_only",
            "source": {"type": "system_requirement", "reference": "油脂提取实验流程.docx", "sections": ["皮革油脂抽提实验流程"]},
            "inputs": {"type": "object", "additionalProperties": False, "required": list(properties), "properties": properties},
            "outputs": {"type": "object", "required": outputs, "properties": {field: {"type": "number" if field in {"mass_g", "temperature_c", "flow_rate"} else "boolean"} for field in outputs}},
            "operation_tree": {"type": "sequence", "children": [{"instance_id": "action_01", "type": "atomic_node", "node_ref": op_id.replace(".meta.", ".action."), "name": name, "source_type": "reserved_interface", "execution_policy": "interface_only", "parameter_bindings": {key: f"inputs.{key}" for key in properties}}]},
            "precondition_refs": [], "physical_requirements": ["设备、对象、接近位姿和控制配置已登记并验证", "反馈及异常停止接口可用；化学相容性与方法经负责人确认"],
            "capability_boundary": {"allowed": ["作为已审核流程中的单步接口"], "forbidden": ["接口登记视为实机可执行", "推测未确认的设备参数或安全条件"]},
            "failure_policy": {"default_action": "stop", "max_retries": 0},
            "extensions": {"operation_granularity": "single_action", "scenario": "leather_fat_extraction", "hardware_binding": "pending"},
        }
        if instrument:
            op["instrument_id"] = instrument
        library["meta_operations"].append(op)
    monitor = next(op for op in library["meta_operations"] if op["id"] == "robot.meta.monitor_reflux")
    monitor["version"] = "1.1.0"
    monitor["outputs"]["properties"]["completed_cycles"] = {"type": "integer", "minimum": 0, "description": "由已验证监测接口提供的累计完整回流循环数，不按经过时间推算"}
    if "completed_cycles" not in monitor["outputs"]["required"]:
        monitor["outputs"]["required"].append("completed_cycles")
    library.update(schema_version="1.7.1", updated_at="2026-10-26T00:00:00Z")
    write("data/meta-operations.json", library)
    templates = json.loads((ROOT / "data/robot-action-templates.json").read_text(encoding="utf-8"))
    templates["library_version"] = "1.7.1"
    write("data/robot-action-templates.json", templates)

    parameters = {}
    def param(key, label, unit, minimum, maximum, anchors, default=None, quote=None, integer=False):
        parameters[key] = {"label": label, "unit": unit, "minimum": minimum, "maximum": maximum, "anchors": anchors, "integer": integer}
        if default is not None:
            parameters[key].update(default=default, document_quote=quote)
    param("cut_size_cm", "皮革切块边长", "cm", 0.1, 10, ["切块", "皮革"], 3, "将待测皮革剪成约3 cm × 3 cm的小块")
    param("max_cut_actions", "剪切最大次数", "次", 1, 200, ["剪切"], None, integer=True)
    param("sample_dry_temperature_c", "水分测定干燥温度", "℃", 1, 300, ["水分"], None)
    param("sample_dry_minutes", "水分测定干燥时长", "min", 1, 10080, ["水分"], None)
    param("oven_temperature_c", "容器干燥温度", "℃", 1, 300, ["容器", "称量瓶"], 105, "称量瓶放入105℃烘箱中干燥")
    param("initial_dry_minutes", "容器首次干燥时长", "min", 1, 10080, ["首次", "称量瓶"], 360, "称量瓶干燥约6 h")
    param("repeat_dry_minutes", "容器重复干燥时长", "min", 1, 1440, ["再次", "重复"], 60, "再次将称量瓶放回烘箱中干燥约1 h")
    param("cool_minutes", "干燥器冷却时长", "min", 1, 1440, ["干燥器", "冷却"], 30, "干燥器中冷却约30 min")
    param("weighing_threshold_mg", "称量瓶恒重阈值", "mg", 0.01, 1000, ["称量瓶"], 5, "连续两次称量质量差小于5 mg")
    param("empty_threshold_mg", "空抽提瓶恒重阈值", "mg", 0.01, 1000, ["空抽提瓶"], None)
    param("empty_dry_temperature_c", "空抽提瓶干燥温度", "℃", 1, 300, ["空抽提瓶"], None)
    param("empty_initial_dry_minutes", "空抽提瓶首次干燥时长", "min", 1, 10080, ["空抽提瓶"], None)
    param("empty_repeat_dry_minutes", "空抽提瓶重复干燥时长", "min", 1, 1440, ["空抽提瓶"], None)
    param("final_threshold_mg", "最终恒重阈值", "mg", 0.01, 1000, ["最终"], None)
    param("sample_target_g", "抽提取样目标质量", "g", 0.01, 1000, ["取样", "抽提样品"], 5, "取约5 g左右皮革样品；实际质量以称量结果为准")
    param("solvent_ml", "二氯甲烷用量", "mL", 0.01, 10000, ["二氯甲烷"], None)
    param("bath_temperature_c", "抽提水浴温度", "℃", 1, 100, ["水浴"], None)
    param("minimum_reflux_cycles", "最低回流循环次数", "次", 30, 10000, ["回流"], 30, "用户补充：按规定完成至少30次溶剂回流循环后，停止加热", integer=True)
    parameters["minimum_reflux_cycles"]["default_source"] = "user_supplement"
    param("extraction_timeout_hours", "抽提最长允许时长", "h", 0.1, 168, ["抽提"], None)
    param("recovery_temperature_c", "蒸馏回收加热温度", "℃", 1, 200, ["蒸馏", "回收"], None)
    param("monitor_minutes", "回流检查间隔", "min", 0.1, 60, ["回流", "检查间隔"], None)
    param("cool_limit_c", "允许拆卸温度上限", "℃", 1, 100, ["拆卸"], None)
    param("max_cycles", "恒重最大循环次数", "次", 1, 20, ["循环"], None, integer=True)
    param("cool_timeout_minutes", "冷却最长等待时长", "min", 1, 1440, ["冷却"], None)
    param("residue_dry_temperature_c", "抽提物干燥温度", "℃", 1, 300, ["抽提物"], None)
    param("residue_dry_minutes", "抽提物干燥时长", "min", 1, 10080, ["抽提物"], None)
    param("solvent_timeout_minutes", "溶剂去除最长时长", "min", 1, 1440, ["溶剂去除"], None)

    nodes = []
    def add(node_id, label, op=None, requires=(), kind="action", **extra):
        node = {"id": node_id, "label": label, "kind": kind, "requires": list(requires), **extra}
        if op:
            node["operation_id"] = op
        if nodes and "next" not in nodes[-1] and nodes[-1]["kind"] not in {"loop_check", "decision", "end"}:
            nodes[-1]["next"] = node_id
        nodes.append(node)
        return node
    def action(node_id, op, label=None, requires=(), **extra):
        operation = next(o for o in library["meta_operations"] if o["id"] == op)
        return add(node_id, label or operation["name"], op, requires, outputs=list(operation["outputs"]["properties"]), **extra)
    def wait(node_id, label, duration, **extra):
        return add(node_id, label, requires=[duration], kind="wait", duration_ref=duration, **extra)
    def transfer(prefix, object_id, target):
        action(prefix + "_pick", "robot.meta.envelop_grasp", f"抓取{object_id}")
        action(prefix + "_move", "robot.meta.move_grasped_object", f"将{object_id}移至{target}")
        action(prefix + "_release", "robot.meta.release_object", f"放置{object_id}")
    def dry(prefix, temperature, duration, object_name):
        action(prefix + "_open", "robot.meta.open_device_door", "打开烘箱门")
        transfer(prefix + "_load", object_name, "烘箱")
        action(prefix + "_close", "robot.meta.close_device_door", "关闭烘箱门")
        action(prefix + "_set", "drying_oven.meta.set_temperature", requires=[temperature])
        action(prefix + "_start", "drying_oven.meta.start")
        wait(prefix + "_wait", "等待干燥并持续监测温度与互锁", duration, guard="oven_feedback_and_interlocks_ok", on_error="oven_safe_stop", on_timeout="oven_safe_stop")
        action(prefix + "_stop", "drying_oven.meta.stop")
        add(prefix + "_safe", "等待满足烘箱安全取物条件", kind="guard", on_timeout="review", requires=["cool_timeout_minutes"], check="safe_unload_profile")
        action(prefix + "_unload_open", "robot.meta.open_device_door", "打开烘箱取物")
        transfer(prefix + "_unload", object_name, "干燥器")
        action(prefix + "_unload_close", "robot.meta.close_device_door", "关闭烘箱门")
        wait(prefix + "_cool", "在干燥器中冷却", "cool_minutes")
    def constant(prefix, object_name, threshold, temp="oven_temperature_c", first="initial_dry_minutes", repeat="repeat_dry_minutes"):
        dry(prefix + "_initial", temp, first, object_name)
        transfer(prefix + "_baseline_transfer", object_name, "天平")
        action(prefix + "_baseline", "robot.meta.read_balance_mass", f"称量{object_name}初始质量", state_updates={prefix + "_previous_g": "result.mass_g"}, guard="stable")
        loop_entry = prefix + "_repeat_open"
        dry(prefix + "_repeat", temp, repeat, object_name)
        transfer(prefix + "_current_transfer", object_name, "天平")
        current = prefix + "_current"
        action(current, "robot.meta.read_balance_mass", f"再次称量{object_name}", guard="stable")
        check = add(prefix + "_check", f"{object_name}达到恒重吗？", kind="loop_check", requires=[threshold, "max_cycles"],
                    data_refs=[current + ".mass_g"], previous_state_ref=prefix + "_previous_g", threshold_ref=threshold,
                    comparison="abs(current_g - previous_g) * 1000 < threshold_mg", max_iterations_ref="max_cycles",
                    on_fail=loop_entry, on_limit="review", outputs=["constant_mass_g"],
                    repeat_state_updates={prefix + "_previous_g": current + ".mass_g"}, counter_id=prefix + "_cycles")
        return check

    add("start", "皮革油脂抽提任务", kind="start")
    action("ventilation", "lab.meta.verify_ventilation", guard="ventilation_ok", on_error="review")
    action("cut", "robot.meta.cut_leather", "执行一次皮革剪切", ["cut_size_cm"])
    add("cut_size_check", "皮革切块尺寸与数量满足要求了吗？", kind="decision", requires=["cut_size_cm", "max_cut_actions"],
        check="registered_cut_geometry_inspection", on_pass="rinse_weighing", on_fail="cut", on_limit="review", max_iterations_ref="max_cut_actions", counter_id="cut_actions")
    action("rinse_weighing", "robot.meta.rinse_vessel", "清洗称量瓶")
    weighing = constant("weighing", "称量瓶", "weighing_threshold_mg")
    weighing["on_pass"] = "wet_sample_load"
    action("wet_sample_load", "robot.meta.transfer_solid_piece", "向称量瓶放入水分测定试样")
    action("wet_mass", "robot.meta.read_balance_mass", "称量瓶与湿试样总质量", guard="stable")
    dry("moisture", "sample_dry_temperature_c", "sample_dry_minutes", "水分测定试样")
    transfer("moisture_mass_transfer", "水分测定试样", "天平")
    action("dry_mass", "robot.meta.read_balance_mass", "称量瓶与干试样总质量", guard="stable")
    add("moisture_fraction", "计算样品水分比例", kind="compute", formula="moisture_fraction",
        data_refs=["weighing_check.constant_mass_g", "wet_mass.mass_g", "dry_mass.mass_g"], outputs=["moisture_fraction"])
    transfer("sample_tare_container", "抽提试样容器", "天平")
    action("sample_tare", "balance.meta.tare", "抽提试样容器置于天平后去皮")
    action("target_sample", "robot.meta.transfer_solid_piece", "选取抽提试样（称量确认实际质量）", ["sample_target_g"])
    action("sample_mass", "robot.meta.read_balance_mass", "记录抽提试样实际净质量", guard="stable_and_net_mass")
    action("cotton_bottom", "robot.meta.place_cotton", "放置滤纸筒底部脱脂棉")
    action("sample_thimble", "robot.meta.insert_extraction_sample")
    action("cotton_top", "robot.meta.place_cotton", "放置滤纸筒上部脱脂棉")
    action("rinse_empty", "robot.meta.rinse_vessel", "清洗空抽提瓶")
    empty = constant("empty", "空抽提瓶", "empty_threshold_mg", "empty_dry_temperature_c", "empty_initial_dry_minutes", "empty_repeat_dry_minutes")
    empty["on_pass"] = "solvent_aspirate"
    action("solvent_aspirate", "robot.meta.aspirate_liquid", "吸取二氯甲烷（工具与材料须审核）", ["solvent_ml"])
    action("solvent_dispense", "robot.meta.dispense_liquid", "向抽提瓶加入二氯甲烷", ["solvent_ml"])
    transfer("thimble", "滤纸筒", "索氏抽提器")
    action("joint_lower", "robot.meta.connect_glass_joint", "连接抽提瓶与索氏抽提器")
    action("joint_upper", "robot.meta.connect_glass_joint", "连接索氏抽提器与冷凝管")
    action("clamp", "robot.meta.fasten_clamp")
    action("inspect_assembly", "robot.meta.inspect_extraction_assembly", guard="assembly_ready", on_error="review")
    action("water_on", "condenser.meta.open_water")
    action("flow", "condenser.meta.read_flow", guard="approved_cooling_flow_profile", on_error="review")
    action("bath_set", "water_bath.meta.set_temperature", requires=["bath_temperature_c"])
    action("bath_start", "water_bath.meta.start")
    add("reflux_watch", "监测累计完整回流次数，至少30次后才可结束抽提", kind="monitored_hold",
        requires=["minimum_reflux_cycles", "extraction_timeout_hours", "monitor_minutes"], operation_id="robot.meta.monitor_reflux",
        duration_ref="extraction_timeout_hours", duration_role="safety_timeout_only", interval_ref="monitor_minutes",
        completion_check="verified_completed_cycles_at_least_required", minimum_count_ref="minimum_reflux_cycles",
        guard="reflux_ok_and_siphon_ok_and_condensation_ok", on_error="safe_stop", on_timeout="safe_stop", outputs=["extraction_completed", "completed_cycles"])
    action("bath_stop", "water_bath.meta.stop")
    action("read_cool", "robot.meta.check_temperature", "监测装置冷却温度", ["cool_limit_c"])
    add("cool_guard", "装置达到允许拆卸温度了吗？", kind="guard", requires=["cool_limit_c", "cool_timeout_minutes"],
        data_refs=["read_cool.temperature_c"], check="temperature_at_or_below_limit", polling_operation="robot.meta.check_temperature", on_timeout="review")
    action("water_off", "condenser.meta.close_water")
    action("unclamp", "robot.meta.release_clamp")
    action("joint_upper_off", "robot.meta.disconnect_glass_joint", "分离冷凝管与抽提器")
    action("joint_lower_off", "robot.meta.disconnect_glass_joint", "分离抽提器与抽提瓶")
    transfer("remove_thimble", "装有皮革样品的滤纸筒", "指定样品暂存位置")
    transfer("recovery_flask", "保留萃取液的抽提瓶", "通风橱内蒸馏回收工位")
    action("recovery_ventilation", "lab.meta.verify_ventilation", "核验蒸馏回收工位通风状态", guard="ventilation_ok", on_error="review")
    action("recovery_joint", "robot.meta.connect_glass_joint", "连接抽提瓶与蒸馏回收装置")
    action("recovery_condenser_joint", "robot.meta.connect_glass_joint", "连接蒸馏冷凝回收接口")
    action("recovery_clamp", "robot.meta.fasten_clamp", "固定蒸馏回收装置夹具")
    action("recovery_water_on", "condenser.meta.open_water", "开启蒸馏回收冷凝水")
    action("recovery_flow", "condenser.meta.read_flow", "核验蒸馏回收冷凝水反馈", guard="approved_recovery_flow_profile", on_error="review")
    action("remove_solvent", "solvent_remover.meta.start", "按登记方法受控加热并冷凝回收二氯甲烷", ["recovery_temperature_c"])
    add("solvent_wait", "是否无持续馏出且无明显大量游离溶剂？", kind="guard", requires=["solvent_timeout_minutes"],
        check="no_continuous_distillate_and_no_obvious_bulk_free_solvent", endpoint_role="operational_distillation_endpoint_only",
        monitoring_guard="ventilation_and_cooling_feedback_ok", confirmation="verified_observation_or_operator_confirmation",
        on_error="solvent_safe_stop", on_timeout="solvent_safe_stop")
    action("solvent_stop", "solvent_remover.meta.stop")
    add("recovery_cool", "保持冷凝并等待回收装置满足后续操作条件", kind="guard", requires=["cool_timeout_minutes"], check="approved_recovery_cooling_profile", on_timeout="review")
    action("recovery_water_off", "condenser.meta.close_water", "回收装置冷却确认后关闭冷凝水")
    action("residue_check", "robot.meta.check_solvent_residue", guard="residue_check_passed", on_error="review")
    final = constant("final", "抽提后样品瓶", "final_threshold_mg", "residue_dry_temperature_c", "residue_dry_minutes", "residue_dry_minutes")
    final["on_pass"] = "content"
    add("content", "计算干基二氯甲烷可溶性抽提物含量", kind="compute", formula="extractable_content_dry_basis",
        data_refs=["empty_check.constant_mass_g", "final_check.constant_mass_g", "sample_mass.mass_g", "moisture_fraction.moisture_fraction"],
        outputs=["extract_mass_g", "sample_dry_mass_g", "extractable_content_percent_dry_basis"])
    add("complete", "逻辑流程结束（尚未执行）", kind="end")
    action("safe_stop", "water_bath.meta.stop", "异常时停止水浴加热", next="review")
    action("solvent_safe_stop", "solvent_remover.meta.stop", "异常时停止溶剂去除程序", next="review")
    action("oven_safe_stop", "drying_oven.meta.stop", "异常时停止烘箱加热", next="review")
    add("review", "停止后请求人工复核，不自动继续", kind="end")
    # Every hardware failure routes to review unless an explicit safe-stop route exists.
    for node in nodes:
        if node["kind"] == "action":
            node.setdefault("on_error", "review")
        if node.get("operation_id"):
            operation = next(o for o in library["meta_operations"] if o["id"] == node["operation_id"])
            device = operation.get("instrument_id") or ("balance" if node["operation_id"] == "robot.meta.read_balance_mass" else "soxhlet")
            bindings = {}
            for field in operation["inputs"]["required"]:
                if field == "temperature_c" and node.get("requires"):
                    bindings[field] = {"parameter_ref": node["requires"][0]}
                elif field == "volume_ml":
                    bindings[field] = {"parameter_ref": "solvent_ml"}
                elif field in {"device_id", "control_profile_id", "monitor_profile_id", "sensor_id"}:
                    bindings[field] = {"resource_ref": f"{device}.{field}"}
                elif field == "method_id":
                    bindings[field] = {"method_ref": "solvent_removal_method"}
                else:
                    bindings[field] = {"object_ref": f"{node['id']}.{field}"}
            node["input_bindings"] = bindings
    phase_specs = [
        ("preparation", "1. 样品处理与环境检查", r"^(start|ventilation|cut)"),
        ("weighing", "2. 称量瓶恒重", r"^(rinse_weighing|weighing_)"),
        ("moisture", "3. 测定样品水分", r"^(wet_|moisture|dry_mass)"),
        ("sample", "4. 制备抽提试样", r"^(sample_tare|target_sample|sample_mass|cotton_|sample_thimble)"),
        ("empty", "5. 空抽提瓶恒重", r"^(rinse_empty|empty_)"),
        ("assembly", "6. 加液与装置组装", r"^(solvent_aspirate|solvent_dispense|thimble|joint_lower$|joint_upper$|clamp$|inspect_assembly)"),
        ("extraction", "7. 索氏抽提与过程监测", r"^(water_on|flow$|bath_set|bath_start|reflux_watch)"),
        ("disassembly", "8. 冷却与拆卸", r"^(bath_stop|read_cool|cool_guard|water_off|unclamp|joint_.*_off)"),
        ("recovery", "9. 蒸馏冷凝回收与残留检查", r"^(remove_thimble|recovery_|remove_solvent|solvent_wait|solvent_stop|residue_check)"),
        ("final", "10. 抽提后恒重", r"^final_"),
        ("result", "11. 含量计算与结果汇总", r"^(content|complete)$"),
        ("exceptions", "异常停止与人工复核", r"^(safe_stop|solvent_safe_stop|oven_safe_stop|review)$"),
    ]
    import re
    phases = [{"id": key, "label": label, "exception": key == "exceptions"} for key, label, _ in phase_specs]
    for node in nodes:
        node["phase_id"] = next(key for key, _, pattern in phase_specs if re.search(pattern, node["id"]))
        node["display"] = {}
        if node["kind"] == "loop_check":
            node["display"]["notice"] = "两次质量差小于阈值才通过；否则重复烘干、冷却、称量，达到上限停止复核。"
            node["display"]["branch_labels"] = {"on_fail": "否，更新上次质量后返回"}
        if node["kind"] == "monitored_hold":
            node["display"]["notice"] = "按已验证反馈累计完整回流次数，达到最低次数才可正常结束；时长仅用于超时保护，不按时间推算次数。"
        if node.get("endpoint_role"):
            node["display"]["notice"] = "仅为蒸馏阶段操作性结束参考，不等于完全无残留；仍须按标准进行后续检查、烘干、冷却和称量。"
        if node["id"] == "remove_solvent":
            node["method_requirement"] = "solvent_removal_method"
    for phase in phases:
        if phase["id"] in {"weighing", "empty", "final"}:
            phase["diagram"] = {"shape": "decision", "subtitle": "连续两次质量差小于阈值？", "repeat_lines": ["否：再次干燥", "冷却、称量"], "limit_ref": "max_cycles"}
        elif phase["id"] == "extraction":
            phase["diagram"] = {"subtitle": "完整回流至少{{minimum_reflux_cycles}}次；超时停止复核"}
    write("knowledge/planner_scenarios/leather_extraction.json", {
        "knowledge_id": "autolab.planner.leather_fat_extraction", "version": "0.3.0", "scenario_id": "leather_fat_extraction",
        "review_status": "draft", "source": "油脂提取实验流程.docx及用户2026-10-26补充的30次回流与蒸馏冷凝回收四步方案",
        "scope": "按用户文档与补充方案编排皮革二氯甲烷索氏抽提、水分测定、恒重、至少30次回流后的蒸馏冷凝回收与干基含量计算；不执行硬件。",
        "default_solvent_removal_method_id": "dcm_distillation_recovery_v1",
        "name": "皮革油脂抽提", "entry": "start", "phases": phases,
        "resource_file": "data/leather-extraction-resources.json",
        "method_requirements": [{"id": "solvent_removal_method", "collection": "solvent_removal_methods", "selection_label": "溶剂去除方法", "default_id": "dcm_distillation_recovery_v1", "constraints": {"solvent": "dichloromethane"},
            "clarification": {"described_label": "已说明：蒸馏冷凝回收；设备、条件及标准待确认", "missing_label": "指定溶剂去除方法需登记审核",
                "described_instruction": "四步实际做法已保存并进入流程，不需要重复说明或自己编造方法ID。至少30次回流为抽提完成门槛；观察到蒸馏停止只是阶段性结束参考，不证明无溶剂残留。",
                "missing_instruction": "请核对输入的方法ID，或说明实际做法供维护者登记。",
                "review_notice": "维护者需根据现场设备和适用标准审核，方法描述不自动授权实机执行。", "format": "可以补充设备型号、运行条件、适用标准名称及版本；未知项保留待确认。"}}],
        "limits": {"loop_limit_parameter": "max_cycles", "on_limit": "stop_and_request_review", "on_timeout": "stop_and_request_review"},
        "parameters": parameters, "nodes": nodes,
    })
    resources_path = ROOT / "data/leather-extraction-resources.json"
    if not resources_path.exists():
        write("data/leather-extraction-resources.json", {
            "schema_version": "1.0.0", "notice": "仅声明待绑定资源，不生成虚构坐标或已批准方法。",
            "solvent_removal_methods": [],
            "resources": [{"id": key, "name": name, "device_id": None, "location_id": None, "control_profile_id": None, "status": "pending_binding"}
                          for key, name in {**instruments, "desiccator": "干燥器", "soxhlet": "索氏抽提工位", "ventilation": "通风设施"}.items()],
        })
    package = json.loads((ROOT / "PACKAGE_INFO.json").read_text(encoding="utf-8"))
    data = package["source_data"]
    for category, field in [("instrument", "instrument_meta_operations"), ("robot", "robot_meta_operations"), ("lab", "laboratory_meta_operations")]:
        data[field] = sum(op["category"] == category for op in library["meta_operations"])
    data.update(total_meta_operations=len(library["meta_operations"]), instrument_groups=len(library["instruments"]),
                single_action_operations=sum(len(op["operation_tree"]["children"]) == 1 for op in library["meta_operations"]))
    data["legacy_composite_operations"] = data["total_meta_operations"] - data["single_action_operations"]
    required_files = package["handoff"]["required_files"]
    for file in ["knowledge/planner_scenarios/leather_extraction.json", "schemas/conditional-workflow.schema.json", "data/leather-extraction-resources.json", "docs/LEATHER_EXTRACTION.md"]:
        if file not in required_files:
            required_files.append(file)
    for file in ["knowledge/planner_scenarios/registry.json", "knowledge/planner_scenarios/sample_hold.json", "schemas/process-scenario.schema.json", "docs/CONFIGURED_WORKFLOWS.md"]:
        if file not in required_files:
            required_files.append(file)
    write("PACKAGE_INFO.json", package)
    example = json.loads((ROOT / "examples/planner-result.sample.json").read_text(encoding="utf-8"))
    example["operationChain"]["capabilityLibrary"].update(version="1.7.1", checksum="sha256:" + hashlib.sha256((ROOT / "data/meta-operations.json").read_bytes()).hexdigest())
    write("examples/planner-result.sample.json", example)


if __name__ == "__main__":
    build()
