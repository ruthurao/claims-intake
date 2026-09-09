"""HTTP integration tests for the claims intake service."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from claims.api.routes import create_app
from claims.policy_client import LookupFailureReason, StubPolicyClient

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
CLAIM_REFERENCE = re.compile(r"^CLM-\d{4}-\d{6}$")

INVALID_EXPECTATIONS: dict[str, tuple[int, str, str]] = {
    "INVALID-01": (422, "POLICY_NOT_FOUND", "V-1"),
    "INVALID-02": (422, "LOSS_BEFORE_INCEPTION", "V-2"),
    "INVALID-03": (422, "LOSS_AFTER_EXPIRY", "V-3"),
    "INVALID-04": (422, "AMOUNT_EXCEEDS_LIMIT", "V-4"),
    "INVALID-05": (422, "TYPE_NOT_COVERED", "V-5"),
    "INVALID-06": (409, "DUPLICATE_NOTIFICATION", "V-6"),
    "INVALID-07": (422, "POLICY_CANCELLED", "V-7"),
}

EDGE_EXPECTATIONS: dict[str, tuple[int, str | None, str | None]] = {
    "EDGE-01": (201, None, None),
    "EDGE-02": (201, None, None),
    "EDGE-03": (201, None, None),
    "EDGE-04": (422, "POLICY_CANCELLED", "V-7"),
    "EDGE-05": (422, "LOSS_BEFORE_INCEPTION", "V-2"),
    "EDGE-06": (422, "AMOUNT_EXCEEDS_LIMIT", "V-4"),
    "EDGE-07": (422, "POLICY_NOT_FOUND", "V-1"),
    "EDGE-08": (400, "MALFORMED_REQUEST", None),
    "EDGE-09": (422, "TYPE_NOT_COVERED", "V-5"),
    "EDGE-10": (422, "POLICY_CANCELLED", "V-7"),
    "EDGE-11": (400, "MALFORMED_REQUEST", None),
    "EDGE-12": (400, "MALFORMED_REQUEST", None),
}


def _load_items(filename: str) -> list[dict[str, Any]]:
    raw = json.loads((DATA_DIR / filename).read_text())
    assert isinstance(raw, list)
    return raw


def _item_by_id(filename: str, fixture_id: str) -> dict[str, Any]:
    for item in _load_items(filename):
        if item["id"] == fixture_id:
            return item
    raise KeyError(fixture_id)


def _policies_by_number() -> dict[str, dict[str, Any]]:
    return {item["policy_number"]: item for item in _load_items("policies.json")}


POLICIES = _policies_by_number()


def client_for(
    *,
    fail_with: LookupFailureReason | None = None,
) -> TestClient:
    return TestClient(
        create_app(
            policy_client=StubPolicyClient(fail_with=fail_with),
        )
    )


def valid_payload() -> dict[str, Any]:
    return dict(_item_by_id("fnol_valid.json", "VALID-01")["payload"])


def assert_error(
    response: Any,
    *,
    expected_status: int,
    expected_code: str,
) -> dict[str, Any]:
    assert response.status_code == expected_status
    body = response.json()
    assert body["code"] == expected_code
    assert isinstance(body["message"], str)
    assert isinstance(body["detail"], dict)
    return body["detail"]


def _assert_recorded(response: Any) -> None:
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "recorded"
    assert CLAIM_REFERENCE.fullmatch(body["claim_reference"])


def _assert_rule_detail(detail: dict[str, Any], *, rule: str, payload: dict[str, Any]) -> None:
    assert detail["rule"] == rule
    if rule == "V-1":
        assert detail["policy_number"] == payload["policy_number"]
        return
    policy = POLICIES[payload["policy_number"]]
    if rule == "V-2":
        assert detail["loss_date"] == payload["loss_date"]
        assert detail["effective_date"] == policy["effective_date"]
    elif rule == "V-3":
        assert detail["loss_date"] == payload["loss_date"]
        assert detail["expiry_date"] == policy["expiry_date"]
    elif rule == "V-4":
        assert detail["estimated_amount"] == payload["estimated_amount"]
        assert detail["limit"] == policy["limit"]
    elif rule == "V-5":
        assert detail["claim_type"] == payload["claim_type"]
        assert detail["permitted_claim_types"] == policy["permitted_claim_types"]
    elif rule == "V-7":
        assert detail["loss_date"] == payload["loss_date"]
        assert detail["cancellation_date"] == policy["cancellation_date"]


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(item["payload"], id=str(item["id"]))
        for item in _load_items("fnol_valid.json")
    ],
)
def test_accepts_valid_notification_over_http(payload: dict[str, Any]) -> None:
    _assert_recorded(client_for().post("/notifications", json=payload))


@pytest.mark.parametrize(
    "item",
    [pytest.param(item, id=str(item["id"])) for item in _load_items("fnol_invalid.json")],
)
def test_rejects_invalid_notification_over_http(item: dict[str, Any]) -> None:
    expected_status, expected_code, expected_rule = INVALID_EXPECTATIONS[item["id"]]
    payload = item["payload"]
    client = client_for()

    if item["id"] == "INVALID-06":
        first = client.post("/notifications", json=valid_payload())
        _assert_recorded(first)
        detail = assert_error(
            client.post("/notifications", json=payload),
            expected_status=expected_status,
            expected_code=expected_code,
        )
        assert detail["rule"] == expected_rule
        assert detail["claim_reference"] == first.json()["claim_reference"]
        return

    detail = assert_error(
        client.post("/notifications", json=payload),
        expected_status=expected_status,
        expected_code=expected_code,
    )
    _assert_rule_detail(detail, rule=expected_rule, payload=payload)


@pytest.mark.parametrize(
    "item",
    [pytest.param(item, id=str(item["id"])) for item in _load_items("fnol_edge.json")],
)
def test_classifies_edge_notification_over_http(item: dict[str, Any]) -> None:
    expected_status, expected_code, expected_rule = EDGE_EXPECTATIONS[item["id"]]
    payload = item["payload"]
    response = client_for().post("/notifications", json=payload)

    if expected_status == 201:
        _assert_recorded(response)
        return

    assert expected_code is not None
    detail = assert_error(
        response,
        expected_status=expected_status,
        expected_code=expected_code,
    )
    if expected_rule is not None:
        _assert_rule_detail(detail, rule=expected_rule, payload=payload)
        return

    assert "field" in detail
    assert "reason" in detail
    if item["id"] == "EDGE-08":
        assert detail["field"] == "estimated_amount"
    elif item["id"] == "EDGE-11":
        assert detail["field"] == "claim_type"
    elif item["id"] == "EDGE-12":
        assert detail["field"] == "estimated_amount"


def test_rejects_extra_field_over_http() -> None:
    payload = {**valid_payload(), "unexpected": "reject me"}

    detail = assert_error(
        client_for().post("/notifications", json=payload),
        expected_status=400,
        expected_code="MALFORMED_REQUEST",
    )

    assert "field" in detail
    assert "reason" in detail


@pytest.mark.parametrize(
    ("reason", "expected_status", "expected_code"),
    [
        pytest.param("timeout", 504, "POLICY_MASTER_TIMEOUT", id="policy-master-timeout"),
        pytest.param(
            "unreachable",
            503,
            "POLICY_MASTER_UNAVAILABLE",
            id="policy-master-unreachable",
        ),
        pytest.param(
            "unparsable",
            502,
            "POLICY_MASTER_INVALID_RESPONSE",
            id="policy-master-unparsable",
        ),
    ],
)
def test_maps_policy_lookup_failures_over_http(
    reason: LookupFailureReason,
    expected_status: int,
    expected_code: str,
) -> None:
    payload = valid_payload()
    detail = assert_error(
        client_for(fail_with=reason).post("/notifications", json=payload),
        expected_status=expected_status,
        expected_code=expected_code,
    )

    assert detail["dependency"] == "policy-master"
    assert detail["policy_number"] == payload["policy_number"]


def test_rejects_invalid_json() -> None:
    response = client_for().post(
        "/notifications",
        content="{not valid json",
        headers={"content-type": "application/json"},
    )

    detail = assert_error(
        response,
        expected_status=400,
        expected_code="MALFORMED_REQUEST",
    )

    assert detail["field"] == "body"


def test_rejected_request_is_not_persisted_over_http() -> None:
    client = client_for()
    accepted_payload = valid_payload()
    rejected_payload = {**accepted_payload, "estimated_amount": "50000.01"}

    rejected = client.post("/notifications", json=rejected_payload)
    accepted = client.post("/notifications", json=accepted_payload)

    assert rejected.status_code == 422
    assert rejected.json()["code"] == "AMOUNT_EXCEEDS_LIMIT"
    _assert_recorded(accepted)
