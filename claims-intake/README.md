# Claims Intake Service

A service that accepts a first notice of loss from the claims portal, validates
it against the policy master and the rule table in `docs/api-contract.md`, and
either records a notification and issues a claim reference or refuses the
submission with a specific reason.

It decides whether a notification is well formed and admissible. It does not
decide whether the claim will be paid.

**Current state.** Days 1 through 4 are in place: the contract, the models and
repository, the rule engine (V-1 through V-7), `POST /notifications`,
integration tests, and a runnable image.

## Where things are

| Path | What it holds |
| --- | --- |
| `docs/api-contract.md` | What the service accepts, returns, and refuses. The authority. |
| `docs/requirements-brief.md` | The open work items and their acceptance criteria. |
| `docs/payload-triage.md` | Day 1 classification of the edge payloads. |
| `docs/tool-comparison.md` | Day 4 note on Cursor vs the usual agent. |
| `data/` | Synthetic policies and notification payloads. |
| `src/claims/models.py` | Shape of the request, policy, and recorded notification. |
| `src/claims/repository.py` | In-memory store, claim-reference issuance, duplicate lookup. |
| `src/claims/service.py` | Rule evaluation and `submit_notification`. |
| `src/claims/api/routes.py` | HTTP surface: parse, call the service, map the outcome. |
| `src/claims/api/constants.py` | Contract section 6: code to status. |
| `src/claims/api/responses.py` | Contract section 5: the error envelope. |
| `src/claims/policy_client.py` | Stub policy master over `data/policies.json`. |
| `tests/` | Unit tests mirror `src/claims/`. Integration tests exercise HTTP. |
| `Dockerfile` | Image that runs the service. |

## Working in this repository

You are already inside the lab container. Confirm it before you start:

```
uname -sm     # Linux aarch64
pwd           # /workspace/claims-intake/claims-intake
```

Dependencies are in `.venv`. Do not install anything. From this directory:

```
uv run pytest
uv run ruff check .
uv run mypy
```

`mypy` is configured `strict = true` in `pyproject.toml`. A clean run means the
annotations currently match the code. The same three commands are what CI runs
on a pull request.

## Run the service

From this directory:

```
uv run uvicorn claims.api.routes:app --reload --host 0.0.0.0 --port 8000
```

Swagger UI is at `http://localhost:8000/docs`.

Send a notification that should be accepted:

```
curl -sS -X POST http://localhost:8000/notifications \
  -H "Content-Type: application/json" \
  -d '{
    "policy_number": "MOT-4471",
    "loss_date": "2026-04-02",
    "claim_type": "collision",
    "estimated_amount": "4200.00",
    "description": "Rear ended at a junction."
  }'
```

A recorded notification returns `201` with a `claim_reference` like
`CLM-2026-000001` and `"status": "recorded"`. A body that cannot be interpreted
returns `400`. A rule failure returns `422` or `409`. A policy-master failure
returns `502`, `503`, or `504`. Every non-2xx body is the envelope in contract
section 5. The codes and statuses are the table in section 6.

## Run it from the image

Build for the architecture the service will be deployed on, not the architecture
of this container:

```
docker buildx build --platform linux/amd64 -t claims-intake:day4 --load .
```

Then:

```
docker run --rm -p 8000:8000 claims-intake:day4
```

The same `curl` as above should return `201`.

### Why `--platform linux/amd64`

This container is Linux on ARM (`uname -sm` prints `Linux aarch64`). `docker
build` with no platform flag builds for the CPU of the machine that is building.
That would produce an ARM image, because that is what you are sitting on.

The service is not meant to run on this laptop's architecture. It is meant to
run on `linux/amd64`, which is what CI (`ubuntu-24.04`) and typical servers
are. An image built for ARM will not start there. `--platform linux/amd64` is
how you name the CPU of the place the image will live, instead of inheriting
the CPU of the place you happened to build it.

## Data

Everything in `data/` is synthetic and was authored for this program. It contains
no real client data and no named clients.

| File | What it is |
| --- | --- |
| `data/policies.json` | Stub policy master. |
| `data/fnol_valid.json` | Payloads that should parse as `NotificationRequest`. |
| `data/fnol_invalid.json` | Well-formed payloads that should fail a rule. |
| `data/fnol_edge.json` | Boundary cases. EDGE-08, EDGE-11, EDGE-12 fail at the model. |
