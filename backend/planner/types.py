from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        populate_by_name=True,
        protected_namespaces=(),
    )


class SampleParameters(StrictModel):
    sample_id: str | None = Field(default=None, min_length=1, max_length=100)
    handoff_confirmed: bool | None = None
    operator: str | None = Field(default=None, min_length=1, max_length=100)


class PlannerRequest(StrictModel):
    scenario_id: str = Field(default="vd10_single_sample_demo", min_length=1, max_length=100)
    knowledge_mode: Literal["approved_only", "demo"] = "approved_only"
    model_mode: Literal["deepseek", "deterministic"] = "deepseek"
    workflow_id: str | None = Field(default=None, min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=10000)
    parameters: SampleParameters
    read_results: bool = True
    measurement_repeats: int = Field(default=1, ge=1, le=10)


class CandidateStep(StrictModel):
    operation_id: str
    evidence_ids: list[str] = Field(min_length=1, max_length=10)


class CandidatePlan(StrictModel):
    steps: list[CandidateStep] = Field(max_length=20)
    unresolved_requests: list[str] = Field(default_factory=list, max_length=10)


class PlanStep(StrictModel):
    step_id: str
    operation_id: str
    operation_version: str
    name: str
    parameters: dict
    parameter_sources: dict[str, str]
    depends_on: list[str]
    evidence_ids: list[str]
    capability_status: str
    execution_policy: str
    physical_requirements: list[str]
    precondition_refs: list[str]


class PlannerResult(StrictModel):
    schema_version: Literal["0.2.0"] = "0.2.0"
    plan_id: str
    workflow_id: str | None
    scenario_id: str
    status: Literal[
        "logical_pass", "needs_input", "needs_review", "unsupported",
        "conflict", "model_error",
    ]
    simulation_only: Literal[True] = True
    physical_status: Literal["not_evaluated"] = "not_evaluated"
    execution_allowed: Literal[False] = False
    knowledge: dict
    steps: list[PlanStep]
    issues: list[dict]
    evidence: list[dict]
    generation: dict
