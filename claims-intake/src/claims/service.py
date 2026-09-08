"""Rule evaluation and notification submission.

This module owns the decision. It does not know it was reached over HTTP, which
is why it can be tested by calling a function with a typed object and asserting on
the result with no server running. It does not know where notifications are
stored either. It knows the rules.

`evaluate_policy_exists` ships written. It is the pattern every other rule
follows: take the notification and whatever it needs, decide, and return a
`ValidationOutcome` that names the rule and carries the values the decision was
made on. Nothing prints, nothing raises for an ordinary refusal, and nothing
reaches for a status code, because a status code is a fact about HTTP and this
module does not know about HTTP.

Day 3 assignment. Build the remaining rules test-first against
`docs/api-contract.md` section 4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any

from claims.models import (
    ClaimRecord,
    ErrorCode,
    NotificationRequest,
    Policy,
    RuleFailure,
    RuleId,
)
from claims.policy_client import PolicyClient, PolicyNotFound
from claims.repository import NotificationRepository


@dataclass(frozen=True)
class ValidationOutcome:
    """The result of evaluating one rule, or of evaluating them all.

    `passed` is the only thing a caller has to branch on. When it is false, `rule`
    names the rule that decided it, `code` is the stable contract code, and
    `detail` carries the values that produced the decision so that the person
    reading the eventual error can see which input was wrong.

    There is no status code here. Contract section 6 maps a code to a status, and
    that mapping is applied at the HTTP boundary.
    """

    passed: bool
    rule: str | None = None
    code: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    claim_reference: str | None = None

    @classmethod
    def ok(cls) -> ValidationOutcome:
        return cls(passed=True)

    @classmethod
    def failed(cls, rule: str, code: str, **detail: Any) -> ValidationOutcome:
        return cls(passed=False, rule=rule, code=code, detail=detail)


def evaluate_policy_exists(
    notification: NotificationRequest,
    policy_client: PolicyClient,
) -> ValidationOutcome:
    """V-1. The policy must exist in the policy master.

    This rule is different from the others in one way that matters: it is the only
    one that reaches outside the service, so it is the only one that can fail for
    a reason that is not the caller's fault. `PolicyNotFound` is caught here and
    turned into an ordinary refusal, because a policy that does not exist is a
    fact about the caller's data. `PolicyLookupFailed` is deliberately not caught,
    because the caller did nothing wrong and the HTTP layer has to be able to tell
    the two apart. Contract section 6 fixes what each becomes.

    V-1 short circuits. Every other rule compares against a field on a policy, and
    if there is no policy there is nothing to compare against. Reporting
    LOSS_BEFORE_INCEPTION for a policy number that does not exist is not merely
    unhelpful, it is a false statement about the client's data (WI-0142, AC-4).
    """
    try:
        policy_client.get_policy(notification.policy_number)
    except PolicyNotFound:
        return ValidationOutcome.failed(
            rule="V-1",
            code="POLICY_NOT_FOUND",
            policy_number=notification.policy_number,
        )
    return ValidationOutcome.ok()


def evaluate_loss_after_inception(
    notification: NotificationRequest,
    policy: Policy,
) -> RuleFailure | None:
    """V-2. The loss must not precede policy inception.

    The boundary is stated in contract section 4.2 and in WI-0142 AC-3. A loss on
    the inception date is covered.
    """
    if notification.loss_date < policy.effective_date:
        return RuleFailure(
            rule=RuleId.V2,
            code=ErrorCode.LOSS_BEFORE_INCEPTION,
        )
    return None


def evaluate_loss_before_expiry(
    notification: NotificationRequest,
    policy: Policy,
) -> RuleFailure | None:
    """V-3. The loss must not fall after the policy expiry date."""
    if notification.loss_date > policy.expiry_date:
        return RuleFailure(
            rule=RuleId.V3,
            code=ErrorCode.LOSS_AFTER_EXPIRY,
        )
    return None


def evaluate_amount_within_limit(
    notification: NotificationRequest,
    policy: Policy,
) -> RuleFailure | None:
    """V-4. The estimated amount must not exceed the policy limit.

    An amount equal to the limit is within cover, per contract section 4.2.
    """
    if notification.estimated_amount > policy.limit:
        return RuleFailure(
            rule=RuleId.V4,
            code=ErrorCode.AMOUNT_EXCEEDS_LIMIT,
        )
    return None


def evaluate_claim_type_covered(
    notification: NotificationRequest,
    policy: Policy,
) -> RuleFailure | None:
    """V-5. The claim type must be permitted on the policy's product."""
    if notification.claim_type not in policy.permitted_claim_types:
        return RuleFailure(
            rule=RuleId.V5,
            code=ErrorCode.TYPE_NOT_COVERED,
        )
    return None


def evaluate_policy_cancelled(
    notification: NotificationRequest,
    policy: Policy,
) -> RuleFailure | None:
    """V-7. A loss on or after cancellation is not covered."""
    if (
        policy.cancellation_date is not None
        and notification.loss_date >= policy.cancellation_date
    ):
        return RuleFailure(
            rule=RuleId.V7,
            code=ErrorCode.POLICY_CANCELLED,
        )
    return None


POLICY_RULES: tuple[
    Callable[[NotificationRequest, Policy], RuleFailure | None],
    ...,
] = (
    evaluate_policy_cancelled,
    evaluate_loss_after_inception,
    evaluate_loss_before_expiry,
    evaluate_amount_within_limit,
    evaluate_claim_type_covered,
)


def evaluate_notification(
    notification: NotificationRequest,
    policy: Policy,
) -> RuleFailure | None:
    """Evaluate every rule and return the outcome the caller sees.

    A notification can violate several rules at once and the caller sees one
    reason, so the order this function evaluates in is a caller-visible behavior.
    It is fixed by contract section 4.1 and by nothing else. If you find yourself
    choosing an order here, the contract is incomplete and the fix belongs there.
    """
    for rule in POLICY_RULES:
        failure = rule(notification, policy)
        if failure is not None:
            return failure
    return None


def submit_notification(
    notification: NotificationRequest,
    policy_client: PolicyClient,
    repository: NotificationRepository,
) -> ValidationOutcome:
    """Validate, and record only if every rule passed.

    Nothing is written before the decision is made. A notification is either
    recorded with a claim reference or it does not exist, and there is no state in
    between for a later reader to interpret.
    """
    try:
        policy_record = policy_client.get_policy(notification.policy_number)
    except PolicyNotFound:
        return ValidationOutcome.failed(
            rule="V-1",
            code="POLICY_NOT_FOUND",
            policy_number=notification.policy_number,
        )

    policy = Policy.model_validate(policy_record)
    failure = evaluate_notification(notification, policy)
    if failure is not None:
        return ValidationOutcome.failed(
            rule=failure.rule.value,
            code=failure.code.value,
        )

    # V-6 is evaluated here because duplicate detection requires repository state.
    # Keeping it outside the pure policy rules preserves the contract order without
    # making evaluate_notification perform I/O.
    existing = repository.find_matching(
        notification.policy_number,
        notification.loss_date,
        notification.claim_type,
    )
    if existing is not None:
        return ValidationOutcome.failed(
            rule="V-6",
            code="DUPLICATE_NOTIFICATION",
            claim_reference=existing.claim_reference,
        )

    recorded = repository.record(ClaimRecord.from_notification(notification))
    return ValidationOutcome(passed=True, claim_reference=recorded.claim_reference)
