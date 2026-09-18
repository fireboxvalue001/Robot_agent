import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .service import (
    DocumentIntentConfigurationError,
    DocumentIntentError,
    recognize_document,
    runtime_status,
    to_semantic_params,
)


router = APIRouter(prefix="/api/intent", tags=["document-intent"])
MAX_DOCUMENT_SIZE = 10 * 1024 * 1024


@router.get("/document/status")
def document_intent_status() -> dict:
    return runtime_status()


@router.post("/document")
async def recognize_document_intent(
    document: UploadFile = File(...),
    workflow_id: str | None = Form(default=None, alias="workflowId"),
) -> dict:
    filename = document.filename or "document.pdf"
    if workflow_id is not None and not workflow_id.startswith("wf_"):
        raise HTTPException(status_code=422, detail="workflowId must start with wf_.")
    content = await document.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded document is empty.")
    if len(content) > MAX_DOCUMENT_SIZE:
        raise HTTPException(status_code=413, detail="The document is larger than 10 MB.")
    try:
        result = await asyncio.to_thread(recognize_document, content, filename)
        semantic = to_semantic_params(
            result["intent"], source_text=result["text"], workflow_id=workflow_id,
        )
    except DocumentIntentConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DocumentIntentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "success": True,
        "intent": result["intent"],
        "semanticParams": semantic,
    }
