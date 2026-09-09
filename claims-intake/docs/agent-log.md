# Engineering decision log

- Accepted: the CI workflow runs from `claims-intake/`, where `pyproject.toml`
  and `uv.lock` are located, and installs the pinned `uv` CLI with Python.
  This satisfies acceptance criterion 13's frozen lockfile and three-check
  pipeline requirements.
- Rejected: adding a separate `requirements.txt` for CI. The project already
  declares dependencies in `pyproject.toml` and locks them in `uv.lock`, so a
  second dependency manifest would duplicate and potentially drift from the
  supported `uv sync --frozen` workflow, contrary to acceptance criterion 13.
- Corrected: the first deliberate CI failure was mis-indented and produced a
  workflow run with no jobs. The step was corrected before treating the result
  as a gate observation.
- CI gate observation: the deliberately failing pull-request check was marked
  failed and GitHub prevented the pull request from merging. This confirms that
  the `Checks / checks (pull_request)` status is required by the branch
  protection configuration.
