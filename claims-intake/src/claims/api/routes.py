"""HTTP surface for the claims intake service.

This layer does three things and no more: it parses the request, it calls the
service, and it maps the outcome to a status code. It holds no rule logic. A rule
that appears here is a rule the service layer cannot be tested for.

Day 4 lab. Implement against `docs/api-contract.md` sections 5 and 6.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from claims.models import ErrorCode, NotificationRequest
from claims.policy_client import PolicyClient, PolicyLookupFailed, StubPolicyClient
from claims.repository import NotificationRepository
from claims.service import submit_notification

ERROR_STATUS: dict[str, int] = {
    ErrorCode.POLICY_NOT_FOUND.value: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.POLICY_CANCELLED.value: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.LOSS_BEFORE_INCEPTION.value: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.LOSS_AFTER_EXPIRY.value: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.AMOUNT_EXCEEDS_LIMIT.value: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.TYPE_NOT_COVERED.value: status.HTTP_422_UNPROCESSABLE_ENTITY,
    ErrorCode.DUPLICATE_NOTIFICATION.value: status.HTTP_409_CONFLICT,
}

LOOKUP_FAILURES: dict[str, tuple[str, int, str]] = {
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


def _error_response(
    code: str,
    message: str,
    detail: dict[str, Any],
    response_status: int,
) -> JSONResponse:
    return JSONResponse(
        status_code=response_status,
        content={"code": code, "message": message, "detail": detail},
    )


def create_app(
    policy_client: PolicyClient | None = None,
    repository: NotificationRepository | None = None,
) -> FastAPI:
    """Create the API application with replaceable service dependencies."""
    client = policy_client or StubPolicyClient()
    notification_repository = repository or NotificationRepository()
    app = FastAPI(title="Claims Intake Service")

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        errors = exc.errors()
        first_error = errors[0] if errors else {}
        location = first_error.get("loc", ())
        field = next(
            (part for part in location[1:] if isinstance(part, str)),
            "body",
        )
        return _error_response(
            code=ErrorCode.MALFORMED_REQUEST.value,
            message="Request body could not be interpreted.",
            detail={"field": field, "reason": first_error.get("msg", "invalid request")},
            response_status=status.HTTP_400_BAD_REQUEST,
        )

    @app.post(
        "/notifications",
        response_model=None,
        status_code=status.HTTP_201_CREATED,
    )
    def submit(notification: NotificationRequest) -> dict[str, str] | JSONResponse:
        try:
            outcome = submit_notification(
                notification,
                client,
                notification_repository,
            )
        except PolicyLookupFailed as exc:
            code, response_status, message = LOOKUP_FAILURES[exc.reason]
            return _error_response(
                code=code,
                message=message,
                detail={
                    "dependency": "policy-master",
                    "policy_number": exc.policy_number,
                    "attempted_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
                },
                response_status=response_status,
            )

        if outcome.passed:
            if outcome.claim_reference is None:
                raise RuntimeError("Successful submission did not produce a claim reference")
            return {
                "claim_reference": outcome.claim_reference,
                "status": "recorded",
            }

        code = outcome.code or ErrorCode.MALFORMED_REQUEST.value
        validation_status = ERROR_STATUS.get(code)
        if validation_status is None:
            raise RuntimeError(f"Unhandled validation error code: {code}")
        detail = {"rule": outcome.rule, **outcome.detail}
        if outcome.claim_reference is not None:
            detail["claim_reference"] = outcome.claim_reference
        return _error_response(
            code=code,
            message=code.replace("_", " ").capitalize() + ".",
            detail=detail,
            response_status=validation_status,
        )

    return app


app = create_app()
