"""Compatibility entry points and registered leather-method calculations."""
import math
from decimal import Decimal

from .conditional import metadata as scenario_metadata, plan_conditional, validate_workflow
from .process_parameters import parameter_value as numeric_value, parse_explicit
from .scenarios import ROOT, load_config

SCENARIO_ID = "leather_fat_extraction"


def load_scenario(root=ROOT):
    return load_config(SCENARIO_ID, root)


def metadata(root=ROOT):
    return scenario_metadata(SCENARIO_ID, root)


def plan_extraction(request, model, root=ROOT):
    return plan_conditional(request, model, root)


def constant_mass(previous_g, current_g, threshold_mg, iteration, max_cycles):
    for value in (previous_g, current_g, threshold_mg):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError("质量和阈值必须是有限数值")
    if type(iteration) is not int or type(max_cycles) is not int or min(previous_g, current_g) < 0 or threshold_mg <= 0 or not 1 <= iteration <= max_cycles <= 20:
        raise ValueError("恒重输入超出范围")
    delta_mg = abs(Decimal(str(current_g)) - Decimal(str(previous_g))) * 1000
    passed = delta_mg < Decimal(str(threshold_mg))
    return {"delta_mg": float(delta_mg), "passed": passed, "next": "pass" if passed else "limit" if iteration >= max_cycles else "repeat"}


def calculate_content(empty_g, final_g, sample_g, moisture_fraction):
    for value in (empty_g, final_g, sample_g, moisture_fraction):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError("计算数据必须为有限数值")
    if min(empty_g, final_g) < 0 or sample_g <= 0 or not 0 <= moisture_fraction < 1 or final_g < empty_g:
        raise ValueError("质量数据或水分比例不合理")
    extract_g = final_g - empty_g
    dry_g = sample_g * (1 - moisture_fraction)
    if extract_g > dry_g:
        raise ValueError("抽提物质量超过样品干重，需要复核")
    return {"extract_mass_g": extract_g, "sample_dry_mass_g": dry_g,
            "extractable_content_percent_dry_basis": extract_g / dry_g * 100}


def calculate_moisture(container_g, wet_total_g, dry_total_g):
    for value in (container_g, wet_total_g, dry_total_g):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("称量值必须为有限数值")
    if not 0 <= container_g < dry_total_g <= wet_total_g:
        raise ValueError("水分测定称量值的顺序不合理")
    return {"moisture_fraction": (wet_total_g - dry_total_g) / (wet_total_g - container_g)}


def reflux_completion(completed_cycles, required_cycles):
    if type(completed_cycles) is not int or type(required_cycles) is not int or completed_cycles < 0 or required_cycles < 30:
        raise ValueError("累计循环数须为非负整数，本场景最低回流要求不得少于30次")
    return {"count_condition_met": completed_cycles >= required_cycles, "remaining_cycles": max(0, required_cycles - completed_cycles),
            "notice": "仅比较已提供计数；反馈、异常及其他前置条件仍需独立核验，不控制加热"}
