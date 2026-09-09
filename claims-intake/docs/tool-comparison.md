# Tool Comparison

## Task Context

I used the normal agent to implement the HTTP routes after the rule engine was already in place. I used Cursor for the Dockerfile and integration-test work after the route structure had been established.

## Normal Agent

The normal agent was effective for implementing the HTTP surface because the task required tracing the API contract across multiple files, including the models, policy client, repository, and service layer.

It helped with:

- understanding the existing architecture,
- mapping rule outcomes to HTTP statuses,
- handling malformed requests,
- handling policy lookup failures,
- running Docker-based validation,
- finding and fixing type-checking issues,
- iterating across multiple related files.

The main advantage was repository-wide reasoning and validation rather than editing one isolated file.

## Cursor

Cursor was used for the Dockerfile and HTTP integration tests after the routes were already in place.

It was effective for:

- inspecting the existing project files,
- making focused edits,
- adding the container configuration,
- writing tests around the established HTTP endpoint,
- reviewing changes directly in the editor.

Because the surrounding route structure already existed, these tasks were more localized and required less architectural investigation.

## Preference

I prefer the **normal agent for multi-file implementation and debugging** because it can trace behavior across the repository, run validation, interpret failures, and iterate on related code.

I prefer **Cursor for focused, visually localized changes** where the design is already established and the work mainly involves editing one or two known files.

The tools complement each other: the normal agent is stronger for cross-cutting implementation, while Cursor is more convenient for targeted edits and review.