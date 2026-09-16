import json
import os
import time
import urllib.error
import urllib.request
from typing import Protocol


class PlannerModelError(RuntimeError):
    pass


class PlannerModel(Protocol):
    def generate(self, messages: list[dict], max_tokens: int = 768) -> tuple[str, dict]: ...


class DeepSeekPlannerModel:
    def status(self) -> dict:
        return {
            "runtime": "deepseek_api",
            "configured": bool(os.getenv("DEEPSEEK_API_KEY")),
            "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            "network_inference": True,
        }

    def generate(self, messages: list[dict], max_tokens: int = 768) -> tuple[str, dict]:
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise PlannerModelError("DEEPSEEK_API_KEY is not configured in backend/.env.")

        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        timeout = float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "60"))
        payload = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "stream": False,
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message")
            except Exception:
                detail = None
            raise PlannerModelError(
                f"DeepSeek API returned HTTP {exc.code}: {detail or 'request rejected'}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise PlannerModelError(f"DeepSeek API request failed: {type(exc).__name__}") from exc

        try:
            choice = body["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise PlannerModelError("DeepSeek API returned an unexpected response structure.") from exc
        usage = body.get("usage") or {}
        return content, {
            "used": True,
            "runtime": "deepseek_api",
            "model": body.get("model", model),
            "finish_reason": choice.get("finish_reason"),
            "temperature": 0,
            "max_tokens": max_tokens,
            "prompt_tokens": usage.get("prompt_tokens"),
            "generated_tokens": usage.get("completion_tokens"),
            "total_seconds": round(time.perf_counter() - started, 3),
            "network_inference": True,
        }


class DeterministicPlannerModel:
    """Explicit offline test mode. It is never used as a hidden model fallback."""

    def status(self) -> dict:
        return {"runtime": "deterministic", "configured": True, "network_inference": False}

    def generate(self, messages: list[dict], max_tokens: int = 768) -> tuple[str, dict]:
        context = json.loads(messages[-1]["content"])
        read_results = context["request"]["read_results"]
        steps = []
        for operation in context["retrieved_operations"]:
            if operation["condition"] == "always" or read_results:
                evidence = [operation["evidence_id"]]
                evidence.extend(
                    rule["rule_id"]
                    for rule in context["rules"]
                    if operation["operation_id"] in {rule["before"], rule["after"]}
                )
                steps.append({
                    "operation_id": operation["operation_id"],
                    "evidence_ids": list(dict.fromkeys(evidence)),
                })
        return json.dumps({"steps": steps, "unresolved_requests": []}, ensure_ascii=False), {
            "used": True,
            "runtime": "deterministic",
            "finish_reason": "stop",
            "network_inference": False,
        }


deepseek_model = DeepSeekPlannerModel()
deterministic_model = DeterministicPlannerModel()
