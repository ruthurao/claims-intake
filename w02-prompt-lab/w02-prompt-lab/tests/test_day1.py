"""Day 1 helpers. These tests do not call Ollama."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from promptlab.config import PROJECT_ROOT, Settings
from promptlab.day1 import (
    CASE_IDS,
    NORMAL_NUM_PREDICT,
    TRUNCATION_NUM_PREDICT,
    call_ollama,
    load_extraction_cases,
    load_prompt_template,
    main,
    make_record,
    optional_str,
    token_count,
    truncation_error_type,
)


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


def test_loads_short_medium_and_long_cases() -> None:
    cases = load_extraction_cases()
    assert set(cases) == set(CASE_IDS)
    assert len(cases["E12"]) < len(cases["E07"]) < len(cases["E11"])


def test_missing_case_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases_file = tmp_path / "extraction.jsonl"
    cases_file.write_text('{"id":"E12","source":"short"}\n', encoding="utf-8")
    monkeypatch.setattr("promptlab.day1.CASES_PATH", cases_file)
    with pytest.raises(KeyError, match="E07"):
        load_extraction_cases()


def test_baseline_prompt_has_document_placeholder() -> None:
    template = load_prompt_template()
    filled = template.replace("{document_text}", "POLICY SOURCE")
    assert "{document_text}" in template
    assert "POLICY SOURCE" in filled
    assert "{document_text}" not in filled


def test_length_stop_reason_is_truncation() -> None:
    assert truncation_error_type("length") == "TruncatedResponseError"
    assert truncation_error_type("stop") is None
    assert truncation_error_type(None) is None


def test_optional_str_and_token_count() -> None:
    assert optional_str(None) is None
    assert optional_str("stop") == "stop"
    assert token_count({"prompt_eval_count": 19}, "prompt_eval_count") == 19
    with pytest.raises(TypeError):
        token_count({}, "eval_count")


def test_make_record_maps_ollama_fields() -> None:
    record = make_record(
        run_id="test-run",
        model_id=Settings.from_env().models["mistral"].model_id,
        case_id="E11",
        temperature=0.0,
        num_predict=8,
        payload={
            "prompt_eval_count": 274,
            "eval_count": 8,
            "done_reason": "length",
            "response": "partial",
        },
        latency_ms=368,
        error_type=truncation_error_type("length"),
    )
    assert record.provider == "ollama"
    assert record.task == "extraction"
    assert record.prompt_id == "baseline"
    assert record.prompt_version == "v0"
    assert record.cached_input_tokens is None
    assert record.input_tokens == 274
    assert record.output_tokens == 8
    assert record.max_output_tokens == 8
    assert record.stop_reason == "length"
    assert record.error_type == "TruncatedResponseError"
    assert record.cost_usd == 0.0
    offset = record.timestamp.utcoffset()
    assert offset is not None
    assert offset.total_seconds() == 0


def test_call_ollama_sends_generate_body(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, json: dict[str, Any], timeout: float) -> FakeResponse:
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse(
            {
                "response": "ok",
                "prompt_eval_count": 19,
                "eval_count": 23,
                "done_reason": "stop",
            }
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    payload, latency_ms = call_ollama(
        base_url="http://example.invalid:11434",
        model_id="mistral:7b",
        prompt="hello",
        temperature=0.0,
        num_predict=512,
    )
    assert captured["url"] == "http://example.invalid:11434/api/generate"
    assert captured["json"]["model"] == "mistral:7b"
    assert captured["json"]["prompt"] == "hello"
    assert captured["json"]["stream"] is False
    assert captured["json"]["options"]["temperature"] == 0.0
    assert captured["json"]["options"]["num_predict"] == 512
    assert isinstance(latency_ms, int)
    assert latency_ms >= 0
    assert payload["done_reason"] == "stop"


def test_call_ollama_rejects_non_object_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(*args: object, **kwargs: object) -> FakeResponse:
        return FakeResponse(["not", "an", "object"])

    monkeypatch.setattr(httpx, "post", fake_post)
    with pytest.raises(TypeError, match="JSON object"):
        call_ollama(
            base_url="http://example.invalid:11434",
            model_id="mistral:7b",
            prompt="hello",
            temperature=0.0,
            num_predict=8,
        )


def test_main_writes_three_successes_then_truncation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[dict[str, Any]] = []

    def fake_call_ollama(
        *,
        base_url: str,
        model_id: str,
        prompt: str,
        temperature: float,
        num_predict: int,
    ) -> tuple[dict[str, Any], int]:
        calls.append(
            {
                "model_id": model_id,
                "temperature": temperature,
                "num_predict": num_predict,
                "prompt": prompt,
            }
        )
        if num_predict == TRUNCATION_NUM_PREDICT:
            return (
                {
                    "prompt_eval_count": 274,
                    "eval_count": 8,
                    "done_reason": "length",
                    "response": "partial",
                },
                20,
            )
        return (
            {
                "prompt_eval_count": 200,
                "eval_count": 40,
                "done_reason": "stop",
                "response": "ok",
            },
            50,
        )

    monkeypatch.setattr("promptlab.day1.call_ollama", fake_call_ollama)
    main()

    configured = Settings.from_env().models["mistral"].model_id
    assert [call["num_predict"] for call in calls] == [
        NORMAL_NUM_PREDICT,
        NORMAL_NUM_PREDICT,
        NORMAL_NUM_PREDICT,
        TRUNCATION_NUM_PREDICT,
    ]
    assert all(call["model_id"] == configured for call in calls)
    assert all(call["temperature"] == 0.0 for call in calls)
    assert "mistral:7b" not in (PROJECT_ROOT / "src" / "promptlab" / "day1.py").read_text(
        encoding="utf-8"
    )

    run_files = list((tmp_path / "runs").glob("*.jsonl"))
    assert len(run_files) == 1
    records = [json.loads(line) for line in run_files[0].read_text(encoding="utf-8").splitlines()]
    assert [record["case_id"] for record in records] == ["E12", "E07", "E11", "E11"]
    assert [record["error_type"] for record in records] == [
        None,
        None,
        None,
        "TruncatedResponseError",
    ]
    assert records[3]["stop_reason"] == "length"
    assert records[3]["max_output_tokens"] == TRUNCATION_NUM_PREDICT
    assert all(record["model_id"] == configured for record in records)
