"""Error envelope from contract section 5.

Every non-2xx response is this shape. Building it in one place keeps the
handlers from inventing a second envelope.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from claims.api.constants import ERROR_STATUS, LOOKUP_FAILURES
from claims.models import ErrorCode
from claims.policy_client import PolicyLookupFailed
from claims.service import ValidationOutcome


def error_response(
    code: str,
    message: str,
    detail: dict[str, Any],
    response_status: int,
) -> JSONResponse:
    return JSONResponse(
        status_code=response_status,
        content={"code": code, "message": message, "detail": detail},
    )


def malformed_request(exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    first_error = errors[0] if errors else {}
    location = first_error.get("loc", ())
    field = next(
        (part for part in location[1:] if isinstance(part, str)),
        "body",
    )
    return error_response(
        code=ErrorCode.MALFORMED_REQUEST.value,
        message="Request body could not be interpreted.",
        detail={"field": field, "reason": first_error.get("msg", "invalid request")},
        response_status=status.HTTP_400_BAD_REQUEST,
    )


def lookup_failure(exc: PolicyLookupFailed) -> JSONResponse:
    code, response_status, message = LOOKUP_FAILURES[exc.reason]
    return error_response(
        code=code,
        message=message,
        detail={
            "dependency": "policy-master",
            "policy_number": exc.policy_number,
            "attempted_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        },
        response_status=response_status,
    )


def rule_failure(outcome: ValidationOutcome) -> JSONResponse:
    code = outcome.code or ErrorCode.MALFORMED_REQUEST.value
    validation_status = ERROR_STATUS.get(code)
    if validation_status is None:
        raise RuntimeError(f"Unhandled validation error code: {code}")
    detail = {"rule": outcome.rule, **outcome.detail}
    if outcome.claim_reference is not None:
        detail["claim_reference"] = outcome.claim_reference
    return error_response(
        code=code,
        message=code.replace("_", " ").capitalize() + ".",
        detail=detail,
        response_status=validation_status,
    )
