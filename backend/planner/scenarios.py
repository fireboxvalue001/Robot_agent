"""Trusted, project-local scenario discovery; request text never selects file paths."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def local_json(root, relative, folder):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root / folder) or path.suffix != ".json":
        raise ValueError("Scenario configuration must reference project-local JSON")
    return json.loads(path.read_text(encoding="utf-8"))


def catalog(root=ROOT):
    data = local_json(root, "knowledge/planner_scenarios/registry.json", "knowledge/planner_scenarios")
    entries = data["scenarios"]
    if len({entry["id"] for entry in entries}) != len(entries):
        raise ValueError("Duplicate scenario IDs")
    for entry in entries:
        if entry["engine"] not in {"legacy_linear", "conditional"}:
            raise ValueError("Unknown scenario engine")
        for pattern in entry.get("routing_patterns", []):
            re.compile(pattern)
    return entries


def get_entry(scenario_id, root=ROOT):
    for entry in catalog(root):
        if entry["id"] == scenario_id:
            return entry
    raise KeyError(scenario_id)


def load_config(scenario_id, root=ROOT):
    entry = get_entry(scenario_id, root)
    config = local_json(root, entry["file"], "knowledge/planner_scenarios")
    if config["scenario_id"] != entry["id"]:
        raise ValueError("Scenario ID differs from registry")
    return config


def resolve(text, scenario_id="auto", root=ROOT):
    entries = catalog(root)
    if scenario_id != "auto":
        matches = [get_entry(scenario_id, root)]
    else:
        matches = [entry for entry in entries if entry.get("enabled", True) and
                   any(re.search(pattern, text, re.I) for pattern in entry.get("routing_patterns", []))]
    if len(matches) != 1:
        return {"status": "needs_input", "reason": "ambiguous" if matches else "unmatched", "scenario_id": None,
                "message": "匹配到多个实验场景，请明确选择一个场景；不同场景不会自动拼接。" if matches else "尚未匹配已登记场景，请选择场景或补充实验目标。",
                "candidates": [{"id": entry["id"], "name": entry["name"]} for entry in (matches or entries) if entry.get("enabled", True)]}
    entry = matches[0]
    if not entry.get("enabled", True):
        raise ValueError("Scenario is disabled")
    return {"status": "resolved", "scenario_id": entry["id"], "name": entry["name"],
            "engine": entry["engine"], "ui": entry.get("ui", {})}
