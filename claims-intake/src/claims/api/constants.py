"""Status mapping from contract section 6.

The service returns a code. This table is how that code becomes an HTTP status.
It is not a rule table: the decision already happened.
"""

from __future__ import annotations

from fastapi import status

from claims.models import ErrorCode
from claims.policy_client import LookupFailureReason

ERROR_STATUS: dict[str, int] = {
    ErrorCode.POLICY_NOT_FOUND.value: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.POLICY_CANCELLED.value: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.LOSS_BEFORE_INCEPTION.value: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.LOSS_AFTER_EXPIRY.value: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.AMOUNT_EXCEEDS_LIMIT.value: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.TYPE_NOT_COVERED.value: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.DUPLICATE_NOTIFICATION.value: status.HTTP_409_CONFLICT,
}

LOOKUP_FAILURES: dict[LookupFailureReason, tuple[str, int, str]] = {
    "unreachable": (
        ErrorCode.POLICY_MASTER_UNAVAILABLE.value,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Policy master could not be reached.",
    ),
    "timeout": (
        ErrorCode.POLICY_MASTER_TIMEOUT.value,
        status.HTTP_504_GATEWAY_TIMEOUT,
        "Policy master did not respond in time.",
    ),
    "unparsable": (
        ErrorCode.POLICY_MASTER_INVALID_RESPONSE.value,
        status.HTTP_502_BAD_GATEWAY,
        "Policy master response could not be parsed.",
    ),
}
