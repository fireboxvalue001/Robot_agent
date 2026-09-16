import hashlib
import json
import re
from graphlib import TopologicalSorter
from pathlib import Path

from jsonschema import Draft202012Validator


PROJECT_DIR = Path(__file__).resolve().parents[2]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _terms(text: str) -> set[str]:
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9_.]+", lowered)
    for segment in re.findall(r"[\u4e00-\u9fff]+", lowered):
        tokens.extend(segment[index:index + 2] for index in range(len(segment) - 1))
    return set(tokens)


class KnowledgeStore:
    def __init__(self, project_dir: Path = PROJECT_DIR):
        self.project_dir = Path(project_dir)
        library_path = self.project_dir / "data" / "meta-operations.json"
        library_raw = library_path.read_bytes()
        self.library = json.loads(library_raw.decode("utf-8"))
        schema = _load_json(self.project_dir / "schemas" / "meta-operation-library.schema.json")
        Draft202012Validator(schema).validate(self.library)
        self.library_hash = hashlib.sha256(library_raw).hexdigest()
        self.operations = {item["id"]: item for item in self.library["meta_operations"]}
        if len(self.operations) != len(self.library["meta_operations"]):
            raise ValueError("The meta-operation library contains duplicate IDs.")

        scenario_path = self.project_dir / "knowledge" / "planner_scenarios" / "vd10_single_sample.json"
        self.scenario = _load_json(scenario_path)
        self.rules = self.scenario["rules"]
        self._validate_references()
        scenario_raw = scenario_path.read_bytes()
        self.scenario_hash = hashlib.sha256(scenario_raw).hexdigest()
        self.digest = hashlib.sha256(
            json.dumps({
                "scenario_sha256": self.scenario_hash,
                "library_sha256": self.library_hash,
            }, sort_keys=True).encode("utf-8")
        ).hexdigest()
        self.evidence = self._build_evidence()

    def _validate_references(self) -> None:
        scenario_ids = [item["operation_id"] for item in self.scenario["operations"]]
        if len(set(scenario_ids)) != len(scenario_ids):
            raise ValueError("The planner scenario contains duplicate operation IDs.")
        missing = sorted(set(scenario_ids) - set(self.operations))
        if missing:
            raise ValueError(f"Planner scenario references unknown operation IDs: {missing}")

        graph = {operation_id: set() for operation_id in scenario_ids}
        for entry in self.scenario["operations"]:
            operation = self.operations[entry["operation_id"]]
            if entry["condition"] not in {"always", "read_results"}:
                raise ValueError(f"Unknown planner condition: {entry['condition']}")
            properties = operation["inputs"].get("properties", {})
            unknown = (set(entry.get("parameter_bindings", {})) | set(entry.get("constant_bindings", {}))) - set(properties)
            if unknown:
                raise ValueError(f"Unknown inputs for {operation['id']}: {sorted(unknown)}")
        for rule in self.rules:
            if rule["before"] not in graph or rule["after"] not in graph:
                raise ValueError(f"Planner rule references an unknown operation: {rule['rule_id']}")
            graph[rule["after"]].add(rule["before"])
        tuple(TopologicalSorter(graph).static_order())

    def _build_evidence(self) -> dict[str, dict]:
        records = {
            "scenario:vd10_single_sample": {
                "evidence_id": "scenario:vd10_single_sample",
                "kind": "planner_scenario",
                "source_file": "knowledge/planner_scenarios/vd10_single_sample.json",
                "source_sha256": self.scenario_hash,
                "review_status": self.scenario["review_status"],
                "independently_verified": False,
            }
        }
        for index, operation in enumerate(self.library["meta_operations"]):
            records[f"cap:{operation['id']}"] = {
                "evidence_id": f"cap:{operation['id']}",
                "kind": "provided_capability",
                "source_file": "data/meta-operations.json",
                "source_sha256": self.library_hash,
                "locator": f"/meta_operations/{index}",
                "operation_id": operation["id"],
                "capability_status": operation["status"],
                "independently_verified": False,
            }
        for index, rule in enumerate(self.rules):
            records[rule["rule_id"]] = {
                "evidence_id": rule["rule_id"],
                "kind": "planner_rule",
                "source_file": "knowledge/planner_scenarios/vd10_single_sample.json",
                "source_sha256": self.scenario_hash,
                "locator": f"/rules/{index}",
                "basis": rule["basis"],
                "review_status": self.scenario["review_status"],
                "independently_verified": False,
            }
        return records

    def metadata(self) -> dict:
        return {
            "knowledge_id": self.scenario["knowledge_id"],
            "version": self.scenario["version"],
            "sha256": self.digest,
            "review_status": self.scenario["review_status"],
            "scope": self.scenario["scope"],
            "scenario_id": self.scenario["scenario_id"],
            "source_library_id": self.library["library_id"],
            "source_library_version": self.library["schema_version"],
            "source_operation_count": len(self.operations),
            "scenario_operation_count": len(self.scenario["operations"]),
            "rule_count": len(self.rules),
        }

    def retrieve(self, request) -> list[dict]:
        if request.scenario_id != self.scenario["scenario_id"]:
            return []
        if request.knowledge_mode == "approved_only" and self.scenario["review_status"] != "approved":
            return []
        query_terms = _terms(request.text)
        documents = []
        for entry in self.scenario["operations"]:
            operation = self.operations[entry["operation_id"]]
            searchable = " ".join(filter(None, [
                operation.get("name"), operation.get("description"),
                operation.get("input_hint"), operation.get("output_hint"),
            ]))
            documents.append({
                "operation_id": operation["id"],
                "name": operation["name"],
                "description": operation["description"],
                "condition": entry["condition"],
                "evidence_id": f"cap:{operation['id']}",
                "retrieval_score": len(query_terms & _terms(searchable)),
                "capability_status": operation["status"],
                "execution_policy": operation["execution_policy"],
            })
        # The scoped set is intentionally kept complete so prerequisites are never lost.
        return documents
