"""Contract-first tests for the Day 3 validation and submission layer."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from inspect import signature
from typing import Any

import pytest

from claims.models import ClaimRecord, ErrorCode, NotificationRequest, Policy, RuleFailure, RuleId
from claims.policy_client import PolicyLookupFailed, StubPolicyClient
from claims.repository import NotificationRepository
from claims.service import evaluate_notification, submit_notification


def make_notification(**overrides: object) -> NotificationRequest:
    payload: dict[str, object] = {
        "policy_number": "MOT-4471",
        "loss_date": "2026-04-02",
        "claim_type": "collision",
        "estimated_amount": "4200.00",
        "description": "Rear ended at a junction.",
    }
    payload.update(overrides)
    return NotificationRequest.model_validate(payload)


def make_policy(**overrides: object) -> Policy:
    payload: dict[str, object] = {
        "policy_number": "MOT-4471",
        "product": "personal_auto_standard",
        "effective_date": date(2026, 3, 1),
        "expiry_date": date(2027, 2, 28),
        "cancellation_date": None,
        "limit": Decimal("50000.00"),
        "permitted_claim_types": ("collision", "glass", "weather"),
    }
    payload.update(overrides)
    return Policy.model_validate(payload)


def assert_failure(
    outcome: RuleFailure | None,
    *,
    rule: RuleId,
    code: ErrorCode,
) -> None:
    assert outcome is not None
    assert outcome.rule == rule
    assert outcome.code == code


@pytest.mark.parametrize(
    ("policy_number", "expected_pass"),
    [
        pytest.param("MOT-4471", True, id="policy-exists"),
        pytest.param("mot-4471", False, id="case-sensitive-miss"),
        pytest.param("MOT-9999", False, id="unknown-policy"),
    ],
)
def test_v1_policy_must_exist(
    policy_number: str,
    expected_pass: bool,
) -> None:
    notification = make_notification(policy_number=policy_number)
    outcome = submit_notification(
        notification,
        StubPolicyClient(),
        NotificationRepository(),
    )

    if expected_pass:
        assert outcome.passed is True
    else:
        assert outcome.passed is False
        assert outcome.rule == RuleId.V1.value
        assert outcome.code == ErrorCode.POLICY_NOT_FOUND.value


@pytest.mark.parametrize(
    ("loss_date", "expected_failure"),
    [
        pytest.param("2026-02-28", (RuleId.V2, ErrorCode.LOSS_BEFORE_INCEPTION), id="before-inception"),
        pytest.param("2026-03-01", None, id="on-inception-boundary"),
        pytest.param("2026-03-02", None, id="after-inception"),
    ],
)
def test_v2_loss_cannot_precede_inception(
    loss_date: str,
    expected_failure: tuple[RuleId, ErrorCode] | None,
) -> None:
    outcome = evaluate_notification(
        make_notification(loss_date=loss_date),
        make_policy(),
    )

    if expected_failure is None:
        assert outcome is None
    else:
        assert_failure(outcome, rule=expected_failure[0], code=expected_failure[1])


@pytest.mark.parametrize(
    ("loss_date", "expected_failure"),
    [
        pytest.param("2027-02-27", None, id="before-expiry"),
        pytest.param("2027-02-28", None, id="on-expiry-boundary"),
        pytest.param("2027-03-01", (RuleId.V3, ErrorCode.LOSS_AFTER_EXPIRY), id="after-expiry"),
    ],
)
def test_v3_loss_cannot_follow_expiry(
    loss_date: str,
    expected_failure: tuple[RuleId, ErrorCode] | None,
) -> None:
    outcome = evaluate_notification(
        make_notification(loss_date=loss_date),
        make_policy(),
    )

    if expected_failure is None:
        assert outcome is None
    else:
        assert_failure(outcome, rule=expected_failure[0], code=expected_failure[1])


@pytest.mark.parametrize(
    ("estimated_amount", "expected_failure"),
    [
        pytest.param("49999.99", None, id="below-limit"),
        pytest.param("50000.00", None, id="on-limit-boundary"),
        pytest.param("50000.01", (RuleId.V4, ErrorCode.AMOUNT_EXCEEDS_LIMIT), id="above-limit"),
    ],
)
def test_v4_amount_cannot_exceed_limit(
    estimated_amount: str,
    expected_failure: tuple[RuleId, ErrorCode] | None,
) -> None:
    outcome = evaluate_notification(
        make_notification(estimated_amount=estimated_amount),
        make_policy(),
    )

    if expected_failure is None:
        assert outcome is None
    else:
        assert_failure(outcome, rule=expected_failure[0], code=expected_failure[1])


@pytest.mark.parametrize(
    ("claim_type", "expected_failure"),
    [
        pytest.param("collision", None, id="permitted-type"),
        pytest.param("theft", (RuleId.V5, ErrorCode.TYPE_NOT_COVERED), id="unpermitted-type"),
    ],
)
def test_v5_claim_type_must_be_permitted(
    claim_type: str,
    expected_failure: tuple[RuleId, ErrorCode] | None,
) -> None:
    outcome = evaluate_notification(
        make_notification(claim_type=claim_type),
        make_policy(permitted_claim_types=("collision", "glass")),
    )

    if expected_failure is None:
        assert outcome is None
    else:
        assert_failure(outcome, rule=expected_failure[0], code=expected_failure[1])


@pytest.mark.parametrize(
    ("loss_date", "expected_failure"),
    [
        pytest.param("2026-01-31", None, id="before-cancellation"),
        pytest.param("2026-02-01", (RuleId.V7, ErrorCode.POLICY_CANCELLED), id="on-cancellation-boundary"),
        pytest.param("2026-02-02", (RuleId.V7, ErrorCode.POLICY_CANCELLED), id="after-cancellation"),
    ],
)
def test_v7_loss_on_or_after_cancellation_is_rejected(
    loss_date: str,
    expected_failure: tuple[RuleId, ErrorCode] | None,
) -> None:
    outcome = evaluate_notification(
        make_notification(loss_date=loss_date),
        make_policy(
            effective_date=date(2026, 1, 1),
            cancellation_date=date(2026, 2, 1),
        ),
    )

    if expected_failure is None:
        assert outcome is None
    else:
        assert_failure(outcome, rule=expected_failure[0], code=expected_failure[1])


def test_v7_does_not_apply_when_cancellation_date_is_null() -> None:
    outcome = evaluate_notification(
        make_notification(loss_date="2026-04-02"),
        make_policy(cancellation_date=None),
    )

    assert outcome is None


def test_policy_requires_cancellation_date_to_be_explicit() -> None:
    payload = make_policy().model_dump()
    del payload["cancellation_date"]

    with pytest.raises(ValueError):
        Policy.model_validate(payload)


@pytest.mark.parametrize(
    ("overrides", "is_duplicate"),
    [
        pytest.param({}, True, id="all-three-fields-match"),
        pytest.param({"policy_number": "MOT-4472"}, False, id="policy-differs"),
        pytest.param({"loss_date": "2026-04-03"}, False, id="loss-date-differs"),
        pytest.param({"claim_type": "theft"}, False, id="claim-type-differs"),
    ],
)
def test_v6_duplicate_is_based_on_policy_date_and_type(
    overrides: dict[str, object],
    is_duplicate: bool,
) -> None:
    repository = NotificationRepository()
    first = make_notification()
    repository.record(ClaimRecord.from_notification(first))

    candidate = make_notification(**overrides)
    duplicate = repository.find_matching(
        candidate.policy_number,
        candidate.loss_date,
        candidate.claim_type,
    )
    assert (duplicate is not None) is is_duplicate


def test_rejected_notification_is_not_a_duplicate() -> None:
    repository = NotificationRepository()
    rejected = make_notification(estimated_amount="50000.01")
    outcome = submit_notification(rejected, StubPolicyClient(), repository)

    assert outcome.passed is False
    assert repository.find_matching(
        rejected.policy_number,
        rejected.loss_date,
        rejected.claim_type,
    ) is None


def test_policy_not_found_becomes_v1_failure() -> None:
    notification = make_notification(policy_number="MOT-9999")
    repository = NotificationRepository()

    outcome = submit_notification(notification, StubPolicyClient(), repository)

    assert outcome.passed is False
    assert outcome.rule == RuleId.V1.value
    assert outcome.code == ErrorCode.POLICY_NOT_FOUND.value


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param("timeout", id="policy-master-timeout"),
        pytest.param("unreachable", id="policy-master-unavailable"),
        pytest.param("unparsable", id="policy-master-invalid-response"),
    ],
)
def test_policy_lookup_failure_propagates_with_reason(reason: Any) -> None:
    notification = make_notification()
    repository = NotificationRepository()
    client = StubPolicyClient(fail_with=reason)

    with pytest.raises(PolicyLookupFailed) as raised:
        submit_notification(notification, client, repository)

    assert raised.value.reason == reason


def test_evaluation_order_returns_cancellation_before_later_rules() -> None:
    notification = make_notification(
        loss_date="2026-02-01",
        estimated_amount="50000.01",
        claim_type="theft",
    )
    policy = make_policy(
        cancellation_date=date(2026, 2, 1),
        permitted_claim_types=("collision",),
    )

    outcome = evaluate_notification(notification, policy)

    assert_failure(outcome, rule=RuleId.V7, code=ErrorCode.POLICY_CANCELLED)


def test_evaluate_notification_does_not_use_repository() -> None:
    assert tuple(signature(evaluate_notification).parameters) == ("notification", "policy")

    notification = make_notification()
    policy = make_policy()

    outcome = evaluate_notification(notification, policy)

    assert outcome is None