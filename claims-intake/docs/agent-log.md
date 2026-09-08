# Engineering decision log

- Accepted: the CI workflow runs from `claims-intake/`, where `pyproject.toml`
  and `uv.lock` are located, and installs the pinned `uv` CLI with Python.
- Rejected: adding a separate `requirements.txt` for CI. The project already
  declares dependencies in `pyproject.toml` and locks them in `uv.lock`, so a
  second dependency manifest would duplicate and potentially drift from the
  supported `uv sync --frozen` workflow.
- Corrected: the first deliberate CI failure was mis-indented and produced a
  workflow run with no jobs. The step was corrected before treating the result
  as a gate observation.
- CI gate observation: the corrected deliberate failure has not been verified
  as a merge-blocking required check yet. The repository should not claim that
  the gate blocks merges until a failing pull-request run is observed in the
  branch protection settings.
