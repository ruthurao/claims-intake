"""Persistence for recorded notifications.

An in-memory store is sufficient for Week 1 and is deliberate rather than a
shortcut. The rules do not know where a notification is stored, so replacing this
with a database in a later week is a change to one module.

The duplicate check that `WI-0151` describes is a query against what has been
recorded, which is why it belongs here rather than in the rule table.

Day 2 assignment. Implement against `docs/api-contract.md` section 3.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from claims.models import ClaimRecord, ClaimType, RecordedNotification


class NotificationRepository:
    """Stores recorded notifications and issues claim references."""

    def __init__(self) -> None:
        self._records: list[RecordedNotification] = []
        self._next_sequence: int = 1

    def record(self, claim: ClaimRecord) -> RecordedNotification:
        """Write a notification and return it with its issued claim reference.

        The reference format is fixed by contract section 3. References are unique
        and are never reissued. Only a claim that has passed service validation can
        reach this method.
        """
        if not isinstance(claim, ClaimRecord):
            raise TypeError("record() requires a ClaimRecord approved by the service")
        year = datetime.now(tz=UTC).date().year
        claim_reference = f"CLM-{year}-{self._next_sequence:06d}"
        self._next_sequence += 1
        recorded = RecordedNotification(
            claim_reference=claim_reference,
            policy_number=claim.policy_number,
            loss_date=claim.loss_date,
            claim_type=claim.claim_type,
            estimated_amount=claim.estimated_amount,
            description=claim.description,
        )
        self._records.append(recorded)
        return recorded

    def find_matching(
        self,
        policy_number: str,
        loss_date: date,
        claim_type: ClaimType,
    ) -> RecordedNotification | None:
        """Return an existing recorded notification matching all three values.

        `WI-0151` AC-1 fixes which fields constitute a match. AC-3 is the reason
        this searches recorded notifications only: a submission that was refused
        was never written, so there is nothing for a later one to duplicate.
        """
        for recorded in self._records:
            if (
                recorded.policy_number == policy_number
                and recorded.loss_date == loss_date
                and recorded.claim_type == claim_type
            ):
                return recorded
        return None
