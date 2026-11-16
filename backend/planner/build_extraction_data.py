"""Maintain the document-derived scenario and append its single-action interfaces."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def write(path, value):
    (ROOT / path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build():
    library = json.loads((ROOT / "data/meta-operations.json").read_text(encoding="utf-8"))
    instruments = {"balance": "分析天平", "drying_oven": "烘箱", "water_bath": "水浴设备", "extraction_heater": "抽提装置加热工位",
                   "condenser": "冷凝水装置", "solvent_remover": "溶剂去除设备（待确定方法）", "soxhlet": "索氏抽提器"}
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
        ("robot.meta.collect_solid_fragments", "执行一次固体碎屑收集", None, ["sample_id", "target_object_id"], ["fragments_collected"]),
        ("robot.meta.mix_solid_sample", "混匀固体样品", None, ["sample_id", "mixing_profile_id"], ["mixing_completed"]),
        ("robot.meta.spread_solid_sample", "平铺固体样品", None, ["sample_id", "target_object_id"], ["sample_spread"]),
        ("robot.meta.place_vessel_lid", "放置称量瓶瓶盖", None, ["lid_id", "vessel_id", "placement_state"], ["lid_placed"]),
        ("robot.meta.inspect_liquid_level", "读取抽提室液位", None, ["assembly_id", "inspection_profile_id"], ["level_ratio", "at_siphon_height", "capacity_ok"]),
        ("extraction_heater.meta.set_temperature", "设置抽提工位加热条件", "extraction_heater", ["device_id", "temperature_c"], ["temperature_set"]),
        ("extraction_heater.meta.start", "启动抽提工位加热", "extraction_heater", ["device_id"], ["running"]),
        ("extraction_heater.meta.stop", "停止抽提工位加热", "extraction_heater", ["device_id"], ["stopped"]),
        ("balance.meta.tare", "空容器放上天平后将读数归零", "balance", ["device_id"], ["tare_completed"]),
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
    monitor["version"] = "1.2.0"
    monitor["outputs"]["properties"]["completed_cycles"] = {"type": "integer", "minimum": 0, "description": "由已验证监测接口提供的累计完整回流循环数，不按经过时间推算"}
    if "completed_cycles" not in monitor["outputs"]["required"]:
        monitor["outputs"]["required"].append("completed_cycles")
    monitor["outputs"]["properties"]["completed_cycles"]["description"] = "当前试样及工位在加热抽提后完成的有效回流—虹吸循环数；排除加液虹吸，不以时间推算或汇总其他工位"
    monitor["description"] = "读取指定工位回流、虹吸和冷凝反馈；计数须与独立试样绑定并排除加液虹吸。仅登记监测接口，不声称已接入六工位设备。"
    monitor["source"]["reference"] = "油脂抽提实验步骤(第一次修订).docx"
    monitor["outputs"]["properties"]["siphon_completed"] = {"type": "boolean", "description": "当前观察阶段的一次虹吸已完成；不自动增加加热抽提循环计数"}
    if "siphon_completed" not in monitor["outputs"]["required"]:
        monitor["outputs"]["required"].append("siphon_completed")
    level = next(op for op in library["meta_operations"] if op["id"] == "robot.meta.inspect_liquid_level")
    level["outputs"]["properties"]["level_ratio"] = {"type": "number", "minimum": 0, "maximum": 1}
    lid = next(op for op in library["meta_operations"] if op["id"] == "robot.meta.place_vessel_lid")
    lid["inputs"]["properties"]["placement_state"]["enum"] = ["open_offset", "closed"]
    collect = next(op for op in library["meta_operations"] if op["id"] == "robot.meta.collect_solid_fragments")
    collect["name"] = "执行一次固体碎屑收集"
    collect["operation_tree"]["children"][0]["name"] = collect["name"]
    collect["description"] = "只执行一次指定区域到目标容器的碎屑收集；全部碎屑是否收齐由流程检查，未收齐则有界重复，不在本能力内隐藏循环。"
    for op in library["meta_operations"]:
        if op["id"] in {entry[0] for entry in actions[16:24]}:
            op["source"]["reference"] = "油脂抽提实验步骤(第一次修订).docx"
    next(item for item in library["instruments"] if item["id"] == "soxhlet")["description"] = (
        "通过回流与虹吸完成抽提。下列为与本装置相关的机器人操作；加热和供水由各自设备控制。"
    )
    next(item for item in library["instruments"] if item["id"] == "solvent_remover")["description"] = (
        "通用方法接口。皮革油脂抽提的挥发步骤使用同一抽提加热工位，不代表另有一台溶剂去除设备。"
    )
    related = {
        "soxhlet": {"insert_extraction_sample", "connect_glass_joint", "disconnect_glass_joint",
                    "inspect_extraction_assembly", "inspect_liquid_level", "monitor_reflux"},
        "balance": {"read_balance_mass"},
    }
    for op in library["meta_operations"]:
        for instrument, names in related.items():
            if op["id"] in {f"robot.meta.{name}" for name in names}:
                op.setdefault("extensions", {})["related_instrument_ids"] = [instrument]
        if op["id"] == "balance.meta.tare":
            op["name"] = "空容器放上天平后将读数归零"
            op["description"] = "空容器已放在秤盘上时，将当前显示归零；再放入样品后，可通过称量读取样品净重。本操作不读取质量。"
            op["operation_tree"]["children"][0]["name"] = op["name"]
    library.update(schema_version="1.9.1", updated_at="2026-11-16T00:00:00Z")
    write("data/meta-operations.json", library)
    templates = json.loads((ROOT / "data/robot-action-templates.json").read_text(encoding="utf-8"))
    templates["library_version"] = library["schema_version"]
    write("data/robot-action-templates.json", templates)

    parameters = {}
    def param(key, label, unit, minimum, maximum, anchors, default=None, quote=None, integer=False):
        parameters[key] = {"label": label, "unit": unit, "minimum": minimum, "maximum": maximum, "anchors": anchors, "integer": integer}
        if default is not None:
            parameters[key].update(default=default, document_quote=quote)
    param("cut_size_cm", "皮革切块边长", "cm", 0.1, 10, ["切块", "皮革"], 0.3, "修订稿：剪成约3 mm × 3 mm的小块，换算为0.3 cm；本实验统一制样条件")
    param("max_cut_actions", "剪切最大次数", "次", 1, 200, ["剪切"], None, integer=True)
    param("max_collection_actions", "碎屑收集最大次数", "次", 1, 200, ["碎屑", "收集"], None, integer=True)
    param("sample_dry_temperature_c", "皮样干燥温度", "℃", 1, 300, ["皮样", "样品干燥"], 105, "皮革样品在105℃条件下干燥")
    param("sample_dry_minutes", "皮样首次干燥时长", "min", 1, 10080, ["皮样", "首次"], 360, "皮革样品首次干燥6 h，换算360 min")
    param("sample_repeat_dry_minutes", "皮样复烘时长", "min", 1, 1440, ["皮样", "复烘"], 60, "皮革样品每次复烘1 h，换算60 min")
    param("sample_threshold_mg", "皮样恒重阈值", "mg", 0.01, 5, ["皮样", "恒重"], 5, "皮革样品相邻两次质量差≤5 mg")
    param("oven_temperature_c", "容器干燥温度", "℃", 1, 300, ["容器", "称量瓶"], 105, "称量瓶放入105℃烘箱中干燥")
    param("initial_dry_minutes", "容器首次干燥时长", "min", 1, 10080, ["首次", "称量瓶"], 360, "称量瓶干燥约6 h")
    param("repeat_dry_minutes", "容器重复干燥时长", "min", 1, 1440, ["再次", "重复"], 60, "再次将称量瓶放回烘箱中干燥约1 h")
    param("cool_minutes", "干燥器冷却时长", "min", 1, 1440, ["干燥器", "冷却"], 30, "干燥器中冷却约30 min")
    param("weighing_threshold_mg", "称量瓶恒重阈值", "mg", 0.01, 5, ["称量瓶"], 5, "称量瓶及瓶盖相邻两次质量差≤5 mg")
    param("empty_threshold_mg", "空抽提瓶恒重阈值", "mg", 0.01, 5, ["空抽提瓶"], 5, "空抽提瓶相邻两次质量差≤5 mg")
    param("empty_dry_temperature_c", "空抽提瓶干燥温度", "℃", 1, 300, ["空抽提瓶"], 105, "空抽提瓶放入105℃烘箱")
    param("empty_initial_dry_minutes", "空抽提瓶首次干燥时长", "min", 1, 10080, ["空抽提瓶"], 360, "空抽提瓶首次烘干6 h，换算360 min")
    param("empty_repeat_dry_minutes", "空抽提瓶重复干燥时长", "min", 1, 1440, ["空抽提瓶"], None)
    param("final_threshold_mg", "最终恒重阈值", "mg", 0.01, 5, ["最终"], 5, "抽提瓶及萃取物相邻两次质量差≤5 mg")
    param("sample_target_g", "抽提取样目标质量", "g", 0.01, 1000, ["取样", "抽提样品"], 5, "取约5 g左右皮革样品；实际质量以称量结果为准")
    param("solvent_ml", "二氯甲烷单次加液量", "mL", 0.01, 10000, ["二氯甲烷"], None)
    param("max_doses", "单阶段加液最大次数", "次", 1, 200, ["加液"], None, integer=True)
    param("bath_temperature_c", "抽提工位加热温度", "℃", 1, 200, ["抽提", "加热"], None)
    param("minimum_reflux_cycles", "最低回流循环次数", "次", 30, 10000, ["回流"], 30, "用户补充：按规定完成至少30次溶剂回流循环后，停止加热", integer=True)
    parameters["minimum_reflux_cycles"]["document_quote"] = "修订稿：各工位分别完成至少30次完整回流—虹吸循环；加液虹吸不计数"
    param("extraction_timeout_hours", "抽提最长允许时长", "h", 0.1, 168, ["抽提"], None)
    param("evaporation_temperature_c", "挥发除溶剂加热温度", "℃", 1, 200, ["挥发", "溶剂去除"], None)
    param("monitor_minutes", "回流检查间隔", "min", 0.1, 60, ["回流", "检查间隔"], None)
    param("cool_limit_c", "允许拆卸温度上限", "℃", 1, 100, ["拆卸"], None)
    param("max_cycles", "恒重最大循环次数", "次", 1, 20, ["循环"], None, integer=True)
    param("cool_timeout_minutes", "冷却最长等待时长", "min", 1, 1440, ["冷却"], None)
    param("residue_dry_temperature_c", "萃取物干燥温度", "℃", 1, 300, ["萃取物"], 105, "抽提瓶及萃取物置于105℃烘箱")
    param("residue_dry_minutes", "萃取物首次干燥时长", "min", 1, 10080, ["萃取物", "首次"], 360, "萃取物首次干燥6 h，换算360 min")
    param("residue_repeat_dry_minutes", "萃取物复烘时长", "min", 1, 1440, ["萃取物", "复烘"], 60, "萃取物随后每次复烘1 h，换算60 min")
    param("residue_repeat_cool_minutes", "萃取物复烘后冷却时长", "min", 1, 1440, ["萃取物", "冷却"], None)
    param("solvent_timeout_minutes", "溶剂去除最长时长", "min", 1, 1440, ["溶剂去除"], None)
    param("siphon_timeout_minutes", "单次虹吸完成最长等待", "min", 0.1, 1440, ["虹吸"], None)
    for key, instruction in {
        "solvent_ml": "填写设备与方法允许的单次计量加液量，不是预计总用量；首次虹吸及半高由液位反馈判定，总加入量需累计且不得超过设备容量。",
        "max_doses": "由维护者确认单阶段加液次数保护上限；达到上限停下复核，不能以次数或时间代替液位检查。",
        "empty_repeat_dry_minutes": "修订稿仅给出空瓶首次6 h，未明确复烘时长。请依据确认的方法补充，不自动套用其他阶段。",
        "residue_repeat_cool_minutes": "修订稿给出萃取物首轮冷却30 min，但未明确复烘后冷却时长；请按确认条件补充。",
        "evaporation_temperature_c": "需与已审核实际挥发方法及原工位一致。填写温度不能批准方法或确认设备适用性。",
    }.items():
        parameters[key]["instruction"] = instruction

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
    def dry(prefix, temperature, duration, object_name, cool="cool_minutes", lid=False):
        if lid:
            action(prefix + "_lid_open", "robot.meta.place_vessel_lid", "将称量瓶瓶盖打开或错开放置", lid_state="open_offset")
        action(prefix + "_open", "robot.meta.open_device_door", "打开烘箱门")
        transfer(prefix + "_load", object_name, "烘箱")
        action(prefix + "_close", "robot.meta.close_device_door", "关闭烘箱门")
        action(prefix + "_set", "drying_oven.meta.set_temperature", requires=[temperature])
        action(prefix + "_start", "drying_oven.meta.start")
        wait(prefix + "_wait", "等待干燥并持续监测温度与互锁", duration, guard="oven_feedback_and_interlocks_ok", on_error="oven_safe_stop", on_timeout="oven_safe_stop")
        action(prefix + "_stop", "drying_oven.meta.stop")
        add(prefix + "_safe", "确认停止加热并满足烘箱安全取物条件", kind="guard", on_timeout="review", requires=["cool_timeout_minutes"], data_refs=[prefix + "_stop.stopped"], check="safe_unload_profile")
        action(prefix + "_unload_open", "robot.meta.open_device_door", "打开烘箱取物")
        transfer(prefix + "_unload", object_name, "干燥器")
        if lid:
            action(prefix + "_lid_close", "robot.meta.place_vessel_lid", "取出后盖好称量瓶瓶盖", lid_state="closed")
        action(prefix + "_unload_close", "robot.meta.close_device_door", "关闭烘箱门")
        if cool:
            wait(prefix + "_cool", "在干燥器中冷却", cool)
        else:
            action(prefix + "_cool_read", "robot.meta.check_temperature", "读取干燥器内抽提瓶温度")
            add(prefix + "_cool", "确认抽提瓶在干燥器中冷却至室温", kind="guard", requires=["cool_timeout_minutes"], data_refs=[prefix + "_cool_read.temperature_c"], check="verified_room_temperature", polling_operation="robot.meta.check_temperature", on_timeout="review")
    def constant(prefix, object_name, threshold, temp="oven_temperature_c", first="initial_dry_minutes", repeat="repeat_dry_minutes", cool="cool_minutes", repeat_cool="cool_minutes", lid=False):
        dry(prefix + "_initial", temp, first, object_name, cool, lid)
        transfer(prefix + "_baseline_transfer", object_name, "天平")
        action(prefix + "_baseline", "robot.meta.read_balance_mass", f"称量{object_name}初始质量", state_updates={prefix + "_previous_g": "result.mass_g"}, guard="stable")
        loop_entry = prefix + ("_repeat_lid_open" if lid else "_repeat_open")
        dry(prefix + "_repeat", temp, repeat, object_name, repeat_cool, lid)
        transfer(prefix + "_current_transfer", object_name, "天平")
        current = prefix + "_current"
        action(current, "robot.meta.read_balance_mass", f"再次称量{object_name}", guard="stable")
        check = add(prefix + "_check", f"{object_name}达到恒重吗？", kind="loop_check", requires=[threshold, "max_cycles"],
                    data_refs=[current + ".mass_g"], previous_state_ref=prefix + "_previous_g", threshold_ref=threshold,
                    comparison="abs(current_g - previous_g) * 1000 <= threshold_mg", max_iterations_ref="max_cycles",
                    on_fail=loop_entry, on_limit="review", outputs=["constant_mass_g"],
                    repeat_state_updates={prefix + "_previous_g": current + ".mass_g"}, counter_id=prefix + "_cycles")
        return check

    add("start", "皮革油脂抽提任务", kind="start")
    action("ventilation", "lab.meta.verify_ventilation", guard="ventilation_ok", on_error="review")
    action("rinse_weighing", "robot.meta.rinse_vessel", "清洗、漂洗称量瓶及瓶盖")
    weighing = constant("weighing", "称量瓶及瓶盖", "weighing_threshold_mg", lid=True)
    weighing["on_pass"] = "cut"
    action("cut", "robot.meta.cut_leather", "执行一次皮革剪切", ["cut_size_cm"])
    add("cut_size_check", "皮革切块尺寸与数量满足要求了吗？", kind="decision", requires=["cut_size_cm", "max_cut_actions"],
        check="registered_cut_geometry_inspection", on_pass="collect_fragments", on_fail="cut", on_limit="review", max_iterations_ref="max_cut_actions", counter_id="cut_actions")
    action("collect_fragments", "robot.meta.collect_solid_fragments", "执行一次皮革碎屑收集")
    add("collect_fragments_check", "全部皮革碎屑与皮块已收齐了吗？", kind="decision", requires=["max_collection_actions"], check="registered_fragment_coverage_inspection", on_pass="mix_solid", on_fail="collect_fragments", on_limit="review", max_iterations_ref="max_collection_actions", counter_id="collection_actions")
    action("mix_solid", "robot.meta.mix_solid_sample", "混匀皮革碎屑与皮块")
    add("trial_identity", "核对两份独立平行样编号及当前试样身份", kind="guard", check="registered_trial_manifest_and_identity", on_error="review")
    action("dry_sample_load", "robot.meta.transfer_solid_piece", "将混匀皮样放入已恒重称量瓶")
    action("dry_sample_spread", "robot.meta.spread_solid_sample", "平铺皮样，避免堆积过厚")
    sample_drying = constant("sample_drying", "称量瓶及皮样", "sample_threshold_mg", "sample_dry_temperature_c", "sample_dry_minutes", "sample_repeat_dry_minutes", lid=True)
    sample_drying["on_pass"] = "sample_weighing_setup"
    add("sample_weighing_setup", "确认干样称量方式与天平状态", kind="guard",
        check="confirmed_dry_sample_weighing_setup", on_error="review")
    action("target_sample", "robot.meta.transfer_solid_piece", "选取已恒重干样（目标质量不代替实测）", ["sample_target_g"])
    action("sample_mass", "robot.meta.read_balance_mass", "读取装筒前的干样称量值", guard="stable")
    action("cotton_bottom", "robot.meta.place_cotton", "放置滤纸筒底部脱脂棉")
    action("sample_thimble", "robot.meta.insert_extraction_sample")
    action("cotton_top", "robot.meta.place_cotton", "放置滤纸筒上部脱脂棉")
    add("sample_loaded_mass", "核实实际装入滤纸筒的干样净质量 md", kind="guard",
        check="verified_loaded_dry_sample_mass", data_refs=["sample_mass.mass_g", "sample_thimble.sample_loaded"],
        outputs=["mass_g"], on_error="review")
    action("rinse_empty", "robot.meta.rinse_vessel", "清洗空抽提瓶")
    empty = constant("empty", "空抽提瓶", "empty_threshold_mg", "empty_dry_temperature_c", "empty_initial_dry_minutes", "empty_repeat_dry_minutes", cool=None, repeat_cool=None)
    empty["on_pass"] = "thimble_pick"
    transfer("thimble", "滤纸筒", "索氏抽提器")
    action("joint_lower", "robot.meta.connect_glass_joint", "连接抽提瓶与索氏抽提器")
    add("dose_capacity_guard", "确认下一次加液不会超过设备允许容量", kind="guard", requires=["solvent_ml"], check="registered_capacity_allows_next_dose", on_error="review")
    action("solvent_aspirate", "robot.meta.aspirate_liquid", "吸取单次二氯甲烷加液量（工具与材料须审核）", ["solvent_ml"])
    action("solvent_dispense", "robot.meta.dispense_liquid", "从抽提室上口缓慢加入二氯甲烷", ["solvent_ml"])
    action("initial_level", "robot.meta.inspect_liquid_level", "读取液位并核验设备容量", guard="capacity_ok", on_error="review")
    add("siphon_height", "液面达到虹吸高度了吗？", kind="decision", requires=["max_doses"], data_refs=["initial_level.at_siphon_height"], check="at_siphon_height", on_pass="dosing_siphon", on_fail="dose_capacity_guard", on_limit="review", max_iterations_ref="max_doses", counter_id="initial_doses")
    action("dosing_siphon", "robot.meta.monitor_reflux", "确认加液阶段首次虹吸完成（不计入抽提循环）")
    add("dosing_siphon_guard", "加液阶段首次虹吸已完成吗？", kind="guard", data_refs=["dosing_siphon.siphon_completed"], check="verified_initial_dosing_siphon", on_timeout="review", requires=["siphon_timeout_minutes"])
    add("topup_capacity_guard", "确认补液剂量不会越过半高允许区间或设备容量", kind="guard", requires=["solvent_ml"], check="registered_capacity_and_half_height_headroom_allow_next_dose", on_error="review")
    action("topup_aspirate", "robot.meta.aspirate_liquid", "吸取抽提室补液用二氯甲烷", ["solvent_ml"])
    action("topup_dispense", "robot.meta.dispense_liquid", "从抽提室上口补液至约半高", ["solvent_ml"])
    action("topup_level", "robot.meta.inspect_liquid_level", "核验补液液位及累计容量", guard="capacity_ok_and_not_above_registered_half_height", on_error="review")
    add("half_level", "抽提室液位达到约二分之一了吗？", kind="decision", requires=["max_doses"], data_refs=["topup_level.level_ratio"], check="registered_half_height_tolerance_and_capacity", on_pass="dose_record_guard", on_fail="topup_capacity_guard", on_limit="review", max_iterations_ref="max_doses", counter_id="topup_doses")
    add("dose_record_guard", "核验实际溶剂总加入量及容量记录", kind="guard", data_refs=["solvent_dispense.operation_log", "topup_dispense.operation_log"], check="verified_dose_event_ledger_and_capacity", on_error="review")
    transfer("heater_station", "抽提瓶及抽提器", "对应加热工位")
    action("joint_upper", "robot.meta.connect_glass_joint", "连接索氏抽提器与冷凝管")
    action("clamp", "robot.meta.fasten_clamp")
    action("inspect_assembly", "robot.meta.inspect_extraction_assembly", guard="assembly_ready", on_error="review")
    action("water_on", "condenser.meta.open_water")
    action("flow", "condenser.meta.read_flow", guard="approved_cooling_flow_profile", on_error="review")
    add("startup_check", "确认各已装载工位无泄漏、未密闭且冷凝正常", kind="guard", check="loaded_station_manifest_and_cooling_interlocks", on_error="review")
    action("bath_set", "extraction_heater.meta.set_temperature", requires=["bath_temperature_c"])
    action("bath_start", "extraction_heater.meta.start")
    add("reflux_watch", "监测累计完整回流次数，至少30次后才可结束抽提", kind="monitored_hold",
        requires=["minimum_reflux_cycles", "extraction_timeout_hours", "monitor_minutes"], operation_id="robot.meta.monitor_reflux",
        duration_ref="extraction_timeout_hours", duration_role="safety_timeout_only", interval_ref="monitor_minutes",
        completion_check="verified_completed_cycles_at_least_required", minimum_count_ref="minimum_reflux_cycles",
        guard="reflux_ok_and_siphon_ok_and_condensation_ok", on_error="safe_stop", on_timeout="safe_stop", outputs=["extraction_completed", "completed_cycles"])
    action("return_liquid", "robot.meta.monitor_reflux", "确认萃取液充分虹吸回原抽提瓶")
    add("return_liquid_guard", "萃取液已充分虹吸回原瓶吗？", kind="guard", data_refs=["return_liquid.siphon_completed"], check="verified_liquid_returned_to_original_flask", requires=["siphon_timeout_minutes"], on_timeout="safe_stop")
    action("bath_stop", "extraction_heater.meta.stop")
    add("heater_stopped_guard", "抽提工位停止加热已确认吗？", kind="guard", data_refs=["bath_stop.stopped"], check="verified_heater_stopped", requires=["cool_timeout_minutes"], on_timeout="review")
    action("read_cool", "robot.meta.check_temperature", "监测装置冷却温度", ["cool_limit_c"])
    add("cool_guard", "装置达到允许拆卸温度了吗？", kind="guard", requires=["cool_limit_c", "cool_timeout_minutes"],
        data_refs=["read_cool.temperature_c"], check="temperature_at_or_below_limit", polling_operation="robot.meta.check_temperature", on_timeout="review")
    action("water_off", "condenser.meta.close_water")
    action("unclamp", "robot.meta.release_clamp")
    action("joint_upper_off", "robot.meta.disconnect_glass_joint", "分离冷凝管与抽提器")
    action("joint_lower_off", "robot.meta.disconnect_glass_joint", "分离抽提器与抽提瓶")
    transfer("evaporation_flask", "保留萃取液的抽提瓶", "通风橱内原加热工位")
    action("evaporation_ventilation", "lab.meta.verify_ventilation", "核验实际挥发去除工位通风状态", guard="ventilation_ok", on_error="review")
    add("evaporation_method_gate", "实际挥发方法及原工位适用性已审核吗？", kind="guard", check="approved_evaporation_method_and_hardware", method_requirement="solvent_removal_method", on_error="review")
    action("evaporation_set", "extraction_heater.meta.set_temperature", "设置经审核的挥发去除加热条件", ["evaporation_temperature_c"])
    action("remove_solvent", "solvent_remover.meta.start", "在同一抽提加热工位启动已审核的挥发程序")
    add("solvent_wait", "是否无可见游离溶剂且无暴沸、飞溅？", kind="guard", requires=["solvent_timeout_minutes"],
        check="no_visible_free_solvent_and_no_bumping_or_loss", endpoint_role="operational_evaporation_endpoint_only",
        monitoring_guard="ventilation_and_heater_feedback_ok", confirmation="verified_observation_or_operator_confirmation",
        on_error="solvent_safe_stop", on_timeout="solvent_safe_stop")
    action("solvent_stop", "solvent_remover.meta.stop", "停止同一抽提加热工位的挥发加热")
    add("evaporation_stopped_guard", "实际挥发程序停止加热已确认吗？", kind="guard", data_refs=["solvent_stop.stopped"], check="verified_evaporation_heater_stopped", requires=["cool_timeout_minutes"], on_timeout="review")
    add("evaporation_cool", "等待抽提瓶满足后续安全取放条件", kind="guard", requires=["cool_timeout_minutes"], check="approved_evaporation_cooling_profile", on_timeout="review")
    action("residue_check", "robot.meta.check_solvent_residue", guard="residue_check_passed", on_error="review")
    final = constant("final", "抽提瓶及萃取物", "final_threshold_mg", "residue_dry_temperature_c", "residue_dry_minutes", "residue_repeat_dry_minutes", repeat_cool="residue_repeat_cool_minutes")
    final["on_pass"] = "content"
    add("content", "按实际干样质量计算二氯甲烷萃取物含量", kind="compute", formula="extractable_content_from_dry_sample",
        data_refs=["empty_check.constant_mass_g", "final_check.constant_mass_g", "sample_loaded_mass.mass_g"],
        outputs=["extract_mass_g", "sample_dry_mass_g", "extractable_content_percent_dry_basis"])
    add("complete", "逻辑流程结束（尚未执行）", kind="end")
    action("safe_stop", "extraction_heater.meta.stop", "异常时停止对应抽提工位加热", next="review")
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
            if node["operation_id"].startswith("solvent_remover."):
                device = "extraction_heater"
            bindings = {}
            for field in operation["inputs"]["required"]:
                if field == "temperature_c" and node.get("requires"):
                    bindings[field] = {"parameter_ref": node["requires"][0]}
                elif field == "placement_state":
                    bindings[field] = {"value": node.pop("lid_state")}
                elif field == "volume_ml":
                    bindings[field] = {"parameter_ref": "solvent_ml"}
                elif field in {"device_id", "control_profile_id", "monitor_profile_id", "sensor_id"}:
                    bindings[field] = {"resource_ref": f"{device}.{field}"}
                elif field == "method_id":
                    bindings[field] = {"method_ref": "solvent_removal_method"}
                else:
                    bindings[field] = {"object_ref": f"{node['id']}.{field}"}
            node["input_bindings"] = bindings
            if node["operation_id"] == "robot.meta.monitor_reflux":
                profile = {"dosing_siphon": "dosing_siphon_profile_id", "reflux_watch": "heated_cycle_profile_id", "return_liquid": "return_liquid_profile_id"}[node["id"]]
                bindings["monitor_profile_id"] = {"resource_ref": "soxhlet." + profile}
                bindings["assembly_id"] = {"object_ref": "trial.assembly_id"}
            if node["operation_id"] == "robot.meta.inspect_liquid_level":
                profile = "initial_level_profile_id" if node["id"] == "initial_level" else "half_level_profile_id"
                bindings["inspection_profile_id"] = {"resource_ref": "soxhlet." + profile}
                bindings["assembly_id"] = {"object_ref": "trial.assembly_id"}
    phase_specs = [
        ("task_entry", "任务入口与环境安全检查", r"^(start|ventilation)$"),
        ("weighing", "1. 称量瓶及瓶盖恒重", r"^(rinse_weighing|weighing_)"),
        ("preparation", "2. 皮革剪碎与混匀", r"^(cut|collect_fragments|mix_solid|trial_identity)"),
        ("sample_drying", "3. 皮革样品干燥与恒重", r"^(dry_sample|sample_drying)"),
        ("sample", "4. 干样称量与滤纸筒装填", r"^(sample_weighing_setup|target_sample|sample_mass|cotton_|sample_thimble|sample_loaded_mass)"),
        ("empty", "5. 空抽提瓶恒重", r"^(rinse_empty|empty_)"),
        ("assembly", "6. 抽提室加液与装置安装", r"^(solvent_aspirate|solvent_dispense|dose_|initial_level|siphon_height|dosing_siphon|topup_|half_level|heater_station|thimble|joint_lower$|joint_upper$|clamp$|inspect_assembly)"),
        ("startup", "7. 冷凝检查与抽提启动", r"^(water_on|flow$|startup_check|bath_set|bath_start)"),
        ("extraction", "8. 索氏抽提与独立工位计数", r"^(reflux_watch|return_liquid)"),
        ("disassembly", "9. 停热冷却与安全拆卸", r"^(bath_stop|heater_stopped_guard|read_cool|cool_guard|water_off|unclamp|joint_.*_off)"),
        ("solvent_removal", "挥发除溶剂与后续准入检查", r"^(evaporation_|remove_solvent|solvent_wait|solvent_stop|residue_check)"),
        ("final", "10. 萃取物干燥与恒重", r"^final_"),
        ("result", "11. 含量计算与结果汇总", r"^(content|complete)$"),
        ("exceptions", "异常停止与人工复核", r"^(safe_stop|solvent_safe_stop|oven_safe_stop|review)$"),
    ]
    import re
    phases = [{"id": key, "label": label, "exception": key == "exceptions"} for key, label, _ in phase_specs]
    for node in nodes:
        node["phase_id"] = next(key for key, _, pattern in phase_specs if re.search(pattern, node["id"]))
        node["display"] = {}
        if node["kind"] == "loop_check":
            node["display"]["notice"] = "相邻两次质量差≤阈值（本实验不超过5 mg）才通过；否则更新基准并复烘、冷却、称量，达到上限停止复核。"
            node["display"]["branch_labels"] = {"on_fail": "否，更新上次质量后返回"}
        if node["kind"] == "monitored_hold":
            node["display"]["notice"] = "仅累计本试样及工位加热后的有效完整循环，排除加液虹吸；达到最低次数才可结束。时长仅用于超时保护，不推算次数或累加其他工位。"
        if node.get("endpoint_role"):
            node["display"]["notice"] = "无可见游离溶剂仅是挥发阶段结束参考，不证明无残留或满足烘箱准入；后续状态需独立确认。"
        if node["id"] == "sample_loaded_mass":
            node["display"]["notice"] = "按现场确认的称量及转移核对方式确认同一试样的实际装入净质量；未确认不得将装筒前读数用作 md。"
        if node["id"] == "remove_solvent":
            node["method_requirement"] = "solvent_removal_method"
        if node.get("operation_id"):
            node["display"].update(title=node["label"])
    for phase in phases:
        if phase["id"] in {"weighing", "sample_drying", "empty", "final"}:
            threshold = {"weighing": "weighing_threshold_mg", "sample_drying": "sample_threshold_mg", "empty": "empty_threshold_mg", "final": "final_threshold_mg"}[phase["id"]]
            phase["diagram"] = {"shape": "decision", "subtitle": "相邻两次质量差≤{{" + threshold + "}} mg？", "repeat_lines": ["否：再次干燥", "冷却、称量"], "limit_ref": "max_cycles"}
        elif phase["id"] == "extraction":
            phase["diagram"] = {"subtitle": "各工位≥{{minimum_reflux_cycles}}次；加液虹吸不计数"}
        elif phase["id"] == "preparation":
            phase["diagram"] = {"subtitle": "切块边长{{cut_size_cm}} cm；每样两份独立平行样"}
        elif phase["id"] == "disassembly":
            phase["diagram"] = {"combine_with": "solvent_removal", "combined_label": "9. 停热拆卸与二氯甲烷去除"}
    write("knowledge/planner_scenarios/leather_extraction.json", {
        "knowledge_id": "autolab.planner.leather_fat_extraction", "version": "0.4.0", "scenario_id": "leather_fat_extraction",
        "review_status": "draft", "source": "油脂抽提实验步骤(第一次修订).docx及用户2026-11-04确认的实际挥发流程；参照QB/T 2718—2018，未逐条核验标准全文",
        "scope": "按实际实验流程编排称量瓶恒重、3mm剪碎混匀、皮样恒重、干样装筒、空瓶恒重、抽提室分段加液、至少30次加热后完整虹吸、通风橱内原工位挥发去除、萃取物恒重和实际干样质量计算；不采用水分校正或蒸馏冷凝回收，不执行硬件。",
        "planning_context": {"unit": "one_independent_trial", "parallel_trials_per_sample": 2, "station_capacity": 6,
            "notice": "本图为一份独立试样的可复用流程。每个样品两份平行样分别记录；六工位的试样映射、事件反馈与共用加热调度待设备端绑定，不表示已生成或验证六工位并行执行。"},
        "blocked_request_patterns": [{"pattern": "(?<!不采用)(?<!不使用)(?<!不进行)(?<!不要)(?<!不做)(?<!未采用)(?<!不)(?<!蒸馏)(?:蒸馏(?:冷凝)?回收|冷凝回收)", "phase_ids": ["solvent_removal"], "message": "当前修订场景固定为实际挥发去除，不支持直接改为蒸馏冷凝回收；需另行登记审核的方法和场景。"}],
        "default_solvent_removal_method_id": "dcm_evaporation_actual_v1",
        "name": "皮革油脂抽提", "entry": "start", "phases": phases,
        "resource_file": "data/leather-extraction-resources.json",
        "method_requirements": [{"id": "solvent_removal_method", "collection": "solvent_removal_methods", "selection_label": "溶剂去除方法", "default_id": "dcm_evaporation_actual_v1", "constraints": {"solvent": "dichloromethane", "method_type": "evaporation"},
            "clarification": {"described_label": "实际挥发流程已说明；原加热工位、通风与方法审核待确认", "missing_label": "实际挥发方法需登记审核",
                "described_instruction": "已固定采用实际挥发流程，不需要重复说明或选择其他路线；无可见游离溶剂仅为停止参考，不证明无残留或满足烘箱准入。",
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
    resources = json.loads(resources_path.read_text(encoding="utf-8"))
    if not any(r["id"] == "extraction_heater" for r in resources["resources"]):
        resources["resources"].append({"id": "extraction_heater", "name": "抽提及实际挥发原加热工位（设备类型待绑定）", "device_id": None, "location_id": None, "control_profile_id": None, "status": "pending_binding"})
    if not any(m["id"] == "dcm_evaporation_actual_v1" for m in resources["solvent_removal_methods"]):
        resources["solvent_removal_methods"].append({"id": "dcm_evaporation_actual_v1", "version": "0.1.0", "name": "通风橱内原加热工位实际挥发去除", "solvent": "dichloromethane", "method_type": "evaporation", "review_status": "draft", "description_status": "provided", "source": "油脂抽提实验步骤(第一次修订).docx第7部分第（1）项；用户确认采用实际路径，非标准符合性批准",
            "steps": ["萃取液充分虹吸回原抽提瓶", "停止加热，冷却至允许安全拆卸后分离", "在通风正常的原加热工位按已审核条件去除溶剂", "无可见游离溶剂时停止，防暴沸、飞溅与干烧；独立核验后续烘箱准入"],
            "pending_confirmation": ["原加热工位型号、适用性及停止接口", "挥发加热条件与防暴沸、飞溅措施", "通风、暴露及废气控制与异常反馈", "无可见游离溶剂的观察确认方式及烘箱准入要求", "实验室方法批准及标准符合性核验"], "execution_allowed": False})
    write("data/leather-extraction-resources.json", resources)
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
    example["operationChain"]["capabilityLibrary"].update(version=library["schema_version"], checksum="sha256:" + hashlib.sha256((ROOT / "data/meta-operations.json").read_bytes()).hexdigest())
    write("examples/planner-result.sample.json", example)


if __name__ == "__main__":
    build()
