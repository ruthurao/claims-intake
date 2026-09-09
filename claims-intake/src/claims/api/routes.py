"""HTTP surface for the claims intake service.

This layer does three things and no more: it parses the request, it calls the
service, and it maps the outcome to a status code. It holds no rule logic. A rule
that appears here is a rule the service layer cannot be tested for.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from claims.api.responses import lookup_failure, malformed_request, rule_failure
from claims.models import NotificationRequest
from claims.policy_client import PolicyClient, PolicyLookupFailed, StubPolicyClient
from claims.repository import NotificationRepository
from claims.service import submit_notification


def create_app(
    policy_client: PolicyClient | None = None,
    repository: NotificationRepository | None = None,
) -> FastAPI:
    """Build the API with replaceable dependencies.

    Tests pass a stub client or an empty repository. Production leaves both
    unset and gets the Week 1 defaults: `StubPolicyClient` over `data/policies.json`
    and an in-memory store.
    """
    client = policy_client or StubPolicyClient()
    notification_repository = repository or NotificationRepository()
    app = FastAPI(title="Claims Intake Service")

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        """400: the body could not be interpreted.

        FastAPI raises this before `submit` runs, which is what keeps a missing
        field or a datetime-shaped `loss_date` from arriving as a rule failure.
        Contract section 2.4: the caller's code is wrong, not their data.
        """
        return malformed_request(exc)

    @app.post(
        "/notifications",
        response_model=None,
        status_code=status.HTTP_201_CREATED,
    )
    def submit(notification: NotificationRequest) -> dict[str, str] | JSONResponse:
        """Accept a first notice of loss, or refuse it with a contract code.

        By the time this function runs, FastAPI has already parsed the body into
        a `NotificationRequest`. What remains is the service call and the mapping
        of its three possible endings onto HTTP:

        - `PolicyLookupFailed` — the policy master did not answer. Not the
          caller's fault; section 6 maps the reason to 502 / 503 / 504.
        - `outcome.passed` — recorded. Section 3: 201, a claim reference, and
          `status: recorded`.
        - otherwise — a rule failed. The service already chose the code; we only
          choose the status.
        """
        try:
            outcome = submit_notification(
                notification,
                client,
                notification_repository,
            )
        except PolicyLookupFailed as exc:
            # Deliberately not caught in the service: a missing policy is data,
            # an unreachable policy master is the system. They must not share a
            # handler, or they share a status code.
            return lookup_failure(exc)

        if outcome.passed:
            if outcome.claim_reference is None:
                raise RuntimeError("Successful submission did not produce a claim reference")
            return {
                "claim_reference": outcome.claim_reference,
                "status": "recorded",
            }

        return rule_failure(outcome)

    return app


# ASGI entry point. `uvicorn claims.api.routes:app` imports this object.
app = create_app()
