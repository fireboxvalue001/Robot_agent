from fastapi import APIRouter, HTTPException
from .knowledge import KnowledgeStore

from .model import deepseek_model, deterministic_model
from .service import planner_service
from .types import PlannerRequest
from .conditional import metadata as process_metadata
from .scenarios import catalog, get_entry, load_config, resolve
from .types import StrictModel
from typing import Literal
from pydantic import Field


class ExtractionCalculation(StrictModel):
    calculation: Literal["constant_mass", "moisture", "extractable_content", "reflux_completion"]
    values: dict[str, float | int] = Field(max_length=6)


class ScenarioSelection(StrictModel):
    text: str = Field(min_length=1, max_length=10000)
    scenario_id: str = Field(default="auto", min_length=1, max_length=100)


router = APIRouter(prefix="/api/planner", tags=["logical-planner"])


def planner_runtime_status() -> dict:
    root = planner_service.knowledge.project_dir
    return {
        "knowledge": planner_service.knowledge.metadata(),
        "scenarios": [process_metadata(e["id"], root) if e["engine"] == "conditional" else KnowledgeStore(root, scenario_id=e["id"]).metadata() for e in catalog(root) if e.get("enabled", True)],
        "models": {
            "deepseek": deepseek_model.status(),
            "deterministic": deterministic_model.status(),
        },
    }


@router.get("/status")
def get_planner_status() -> dict:
    return planner_runtime_status()


@router.get("/knowledge")
def get_planner_knowledge(scenario_id: str = "vd10_single_sample_demo") -> dict:
    try:
        root = planner_service.knowledge.project_dir
        if get_entry(scenario_id, root)["engine"] == "conditional":
            return {**process_metadata(scenario_id, root), "process": load_config(scenario_id, root), "contract": "schemas/conditional-workflow.schema.json"}
        store = planner_service.knowledge if scenario_id == "vd10_single_sample_demo" else KnowledgeStore(planner_service.knowledge.project_dir, scenario_id=scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown planner scenario") from exc
    return {
        **store.metadata(),
        "operations": [
            {
                "operation_id": item["operation_id"],
                "condition": item["condition"],
                "name": store.operations[item["operation_id"]]["name"],
            }
            for item in store.scenario["operations"]
        ],
        "rules": store.rules,
        "boundaries": store.scenario["boundaries"],
    }


@router.post("/plan")
def create_logical_plan(request: PlannerRequest) -> dict:
    try:
        return planner_service.plan(request).model_dump(mode="json")
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/scenarios")
def get_scenario_catalog() -> dict:
    return {"scenarios": [{k: e[k] for k in ("id", "name", "engine", "ui") if k in e}
                           for e in catalog(planner_service.knowledge.project_dir) if e.get("enabled", True)]}


@router.post("/resolve")
def resolve_scenario(request: ScenarioSelection) -> dict:
    try:
        return resolve(request.text, request.scenario_id, planner_service.knowledge.project_dir)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/leather-extraction/evaluate")
def evaluate_extraction_data(request: ExtractionCalculation) -> dict:
    from .extraction import calculate_content, calculate_moisture, constant_mass, reflux_completion
    functions = {"constant_mass": constant_mass, "moisture": calculate_moisture, "extractable_content": calculate_content, "reflux_completion": reflux_completion}
    try:
        result = functions[request.calculation](**request.values)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"calculation": request.calculation, "result": result, "execution_allowed": False,
            "notice": "仅校验调用方提供的数据，不代表采集数据或执行设备"}
