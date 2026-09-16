from fastapi import APIRouter

from .model import deepseek_model, deterministic_model
from .service import planner_service
from .types import PlannerRequest


router = APIRouter(prefix="/api/planner", tags=["logical-planner"])


def planner_runtime_status() -> dict:
    return {
        "knowledge": planner_service.knowledge.metadata(),
        "models": {
            "deepseek": deepseek_model.status(),
            "deterministic": deterministic_model.status(),
        },
    }


@router.get("/status")
def get_planner_status() -> dict:
    return planner_runtime_status()


@router.get("/knowledge")
def get_planner_knowledge() -> dict:
    store = planner_service.knowledge
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
    return planner_service.plan(request).model_dump(mode="json")
