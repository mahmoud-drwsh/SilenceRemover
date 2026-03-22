# Review and commit

Run a **code review pass**, then **commit** only if nothing blocking is found. **Do not** run `git push`; the user pushes manually.

## Orchestration rule (strict)

- The **supervising agent does not substitute for subagents**: do not hand-review large diffs, run the full check matrix, or perform **git write** (e.g. commit) yourself when a delegated agent can do it.
- **Delegate** scoped work to subagents (e.g. explore/shell/general-purpose): one message can launch **parallel** agents when steps are independent.
- The supervisor **coordinates**, **merges outcomes**, applies **must-fix** decisions, and delivers the **final summary** to the user.

## 1. Scope (agent)

- **Delegate** a subagent to report `git status`, `git diff`, and touched paths (and whether the tree is clean).
- If the working tree is clean, **stop** after reporting that (nothing to commit).

## 2. Review (agents — required)

- **Must** run the review via **one or more subagents** (e.g. parallel: correctness; style/conventions; secrets/sensitive data including `.env` and accidental staging).
- Subagents read the diff and related files; the supervisor **only synthesizes** findings into must-fix vs nice-to-have.
- **Block** the rest of the workflow if there are **must-fix** issues (bugs, broken imports, likely regressions, secrets in commits). Delegate fixes to an agent or ask the user before proceeding.

## 3. Automated checks (agent)

- **Delegate** a subagent (e.g. shell) to run whatever applies in this repo; skip missing tools gracefully:
  - `uv run python -m compileall -q src packages` — syntax check for packaged code.
  - If `pytest`, `ruff`, or other checks exist in `pyproject.toml` or CI configs, run those too.
- If any command **fails**, **do not** commit; report the failure and stop.

## 4. Commit (agent, only if review + checks are clean)

- **Delegate** a subagent with **git write** permission to: stage intentional paths only (`git add` — **never** secrets or unintended files), write a **clear, conventional** commit message (imperative subject, body if needed), and `git commit`.

## 5. Summary for the user

- What agents reviewed, check results, commit hash or message—or why the workflow stopped early.
