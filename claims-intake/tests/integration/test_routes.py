"""HTTP integration tests for the claims intake service."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from claims.api.routes import create_app
from claims.policy_client import LookupFailureReason, StubPolicyClient


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
    return {
        "policy_number": "MOT-4471",
        "loss_date": "2026-04-02",
        "claim_type": "collision",
        "estimated_amount": "4200.00",
        "description": "Rear ended at a junction.",
    }


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


def test_accepts_notification_and_returns_claim_reference() -> None:
    response = client_for().post("/notifications", json=valid_payload())

    assert response.status_code == 201
    assert response.json()["status"] == "recorded"
    assert response.json()["claim_reference"].startswith("CLM-")


@pytest.mark.parametrize(
    ("payload", "expected_code", "expected_detail"),
    [
        pytest.param(
            {
                **valid_payload(),
                "policy_number": "MOT-9999",
            },
            "POLICY_NOT_FOUND",
            {"rule": "V-1"},
            id="v1-policy-not-found",
        ),
        pytest.param(
            {
                "policy_number": "MOT-4479",
                "loss_date": "2026-02-20",
                "claim_type": "collision",
                "estimated_amount": "5000.00",
            },
            "LOSS_BEFORE_INCEPTION",
            {"rule": "V-2"},
            id="v2-before-inception",
        ),
        pytest.param(
            {
                "policy_number": "MOT-4489",
                "loss_date": "2026-03-20",
                "claim_type": "theft",
                "estimated_amount": "8000.00",
            },
            "LOSS_AFTER_EXPIRY",
            {"rule": "V-3"},
            id="v3-after-expiry",
        ),
        pytest.param(
            {
                "policy_number": "MOT-4502",
                "loss_date": "2026-03-08",
                "claim_type": "collision",
                "estimated_amount": "14500.00",
            },
            "AMOUNT_EXCEEDS_LIMIT",
            {"rule": "V-4"},
            id="v4-over-limit",
        ),
        pytest.param(
            {
                "policy_number": "MOT-4486",
                "loss_date": "2026-03-14",
                "claim_type": "collision",
                "estimated_amount": "6200.00",
            },
            "TYPE_NOT_COVERED",
            {"rule": "V-5"},
            id="v5-type-not-covered",
        ),
        pytest.param(
            {
                "policy_number": "MOT-4496",
                "loss_date": "2026-03-05",
                "claim_type": "glass",
                "estimated_amount": "700.00",
            },
            "POLICY_CANCELLED",
            {"rule": "V-7"},
            id="v7-after-cancellation",
        ),
    ],
)
def test_rejects_each_policy_rule_over_http(
    payload: dict[str, Any],
    expected_code: str,
    expected_detail: dict[str, str],
) -> None:
    response = client_for().post("/notifications", json=payload)

    detail = assert_error(
        response,
        expected_status=422,
        expected_code=expected_code,
    )
    for key, value in expected_detail.items():
        assert detail[key] == value


def test_rejects_duplicate_notification_over_http() -> None:
    client = client_for()
    first = client.post("/notifications", json=valid_payload())
    duplicate = client.post("/notifications", json=valid_payload())

    assert first.status_code == 201
    detail = assert_error(
        duplicate,
        expected_status=409,
        expected_code="DUPLICATE_NOTIFICATION",
    )
    assert detail["rule"] == "V-6"
    assert detail["claim_reference"] == first.json()["claim_reference"]


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(
            {
                "policy_number": "MOT-4471",
                "loss_date": "2026-04-02",
                "claim_type": "collision",
            },
            id="missing-estimated-amount",
        ),
        pytest.param(
            {**valid_payload(), "unexpected": "reject me"},
            id="extra-field",
        ),
    ],
)
def test_rejects_malformed_request_over_http(payload: dict[str, Any]) -> None:
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
    detail = assert_error(
        client_for(fail_with=reason).post("/notifications", json=valid_payload()),
        expected_status=expected_status,
        expected_code=expected_code,
    )

    assert detail["dependency"] == "policy-master"
    assert detail["policy_number"] == "MOT-4471"
