"""Day 1 local Mistral extraction run with usage recording."""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from promptlab.config import PROJECT_ROOT, Settings
from promptlab.usage import CallRecord, append_record, compute_cost

CASE_IDS = ("E12", "E07", "E11")
PROMPT_ID = "baseline"
PROMPT_VERSION = "v0"
NORMAL_NUM_PREDICT = 512
TRUNCATION_NUM_PREDICT = 8
PROMPT_PATH = PROJECT_ROOT / "src" / "prompts" / "baseline.v0.md"
CASES_PATH = PROJECT_ROOT / "cases" / "extraction.jsonl"


def load_extraction_cases() -> dict[str, str]:
    cases: dict[str, str] = {}
    for line in CASES_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload: dict[str, Any] = json.loads(line)
        case_id = str(payload["id"])
        if case_id in CASE_IDS:
            cases[case_id] = str(payload["source"])
    missing = [case_id for case_id in CASE_IDS if case_id not in cases]
    if missing:
        raise KeyError(f"Missing extraction cases: {', '.join(missing)}")
    return cases


def load_prompt_template() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def call_ollama(
    *,
    base_url: str,
    model_id: str,
    prompt: str,
    temperature: float,
    num_predict: int,
) -> tuple[dict[str, Any], int]:
    started = time.perf_counter()
    response = httpx.post(
        f"{base_url}/api/generate",
        json={
            "model": model_id,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
            },
        },
        timeout=300.0,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    response.raise_for_status()
    payload: Any = response.json()
    if not isinstance(payload, dict):
        raise TypeError("Ollama did not return a JSON object")
    return payload, latency_ms


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def token_count(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise TypeError(f"Ollama field {key!r} was missing or not an int")
    return value


def make_record(
    *,
    run_id: str,
    model_id: str,
    case_id: str,
    temperature: float,
    num_predict: int,
    payload: dict[str, Any],
    latency_ms: int,
    error_type: str | None,
) -> CallRecord:
    input_tokens = token_count(payload, "prompt_eval_count")
    output_tokens = token_count(payload, "eval_count")
    return CallRecord(
        record_id=str(uuid.uuid4()),
        run_id=run_id,
        timestamp=datetime.now(UTC),
        provider="ollama",
        model_id=model_id,
        task="extraction",
        case_id=case_id,
        prompt_id=PROMPT_ID,
        prompt_version=PROMPT_VERSION,
        attempt=1,
        temperature=temperature,
        max_output_tokens=num_predict,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=None,
        latency_ms=latency_ms,
        cost_usd=compute_cost(model_id, input_tokens, output_tokens),
        stop_reason=optional_str(payload.get("done_reason")),
        error_type=error_type,
        response_text=optional_str(payload.get("response")),
    )


def main() -> None:
    settings = Settings.from_env()
    model = settings.models["mistral"]
    temperature = 0.0
    run_id = str(uuid.uuid4())
    cases = load_extraction_cases()
    template = load_prompt_template()

    for case_id in CASE_IDS:
        prompt = template.replace("{document_text}", cases[case_id])
        payload, latency_ms = call_ollama(
            base_url=settings.ollama_base_url,
            model_id=model.model_id,
            prompt=prompt,
            temperature=temperature,
            num_predict=NORMAL_NUM_PREDICT,
        )
        record = make_record(
            run_id=run_id,
            model_id=model.model_id,
            case_id=case_id,
            temperature=temperature,
            num_predict=NORMAL_NUM_PREDICT,
            payload=payload,
            latency_ms=latency_ms,
            error_type=None,
        )
        append_record(record, run_id)
        print(
            f"{case_id}: input_tokens={record.input_tokens} "
            f"output_tokens={record.output_tokens} latency_ms={record.latency_ms} "
            f"stop_reason={record.stop_reason}"
        )

    truncation_prompt = template.replace("{document_text}", cases["E11"])
    truncation_payload, truncation_latency_ms = call_ollama(
        base_url=settings.ollama_base_url,
        model_id=model.model_id,
        prompt=truncation_prompt,
        temperature=temperature,
        num_predict=TRUNCATION_NUM_PREDICT,
    )
    truncation_error: str | None = None
    if truncation_payload.get("done_reason") == "length":
        truncation_error = "TruncatedResponseError"
    truncation_record = make_record(
        run_id=run_id,
        model_id=model.model_id,
        case_id="E11",
        temperature=temperature,
        num_predict=TRUNCATION_NUM_PREDICT,
        payload=truncation_payload,
        latency_ms=truncation_latency_ms,
        error_type=truncation_error,
    )
    append_record(truncation_record, run_id)
    print(
        "E11 truncation demo: "
        f"num_predict={TRUNCATION_NUM_PREDICT} "
        f"stop_reason={truncation_record.stop_reason} "
        f"error_type={truncation_record.error_type}"
    )
    print(f"run_id={run_id}")


if __name__ == "__main__":
    main()
