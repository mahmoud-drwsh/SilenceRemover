# Review, commit, and push

Run a **code review pass**, then **commit and push** only if nothing blocking is found.

## 1. Scope

- Review **uncommitted changes** (`git status`, `git diff`) and any files they touch.
- If the working tree is clean, say so and **stop** (nothing to commit).

## 2. Review (use agents)

- **Prefer delegated agents** for the review: e.g. one (or parallel) subagents focused on correctness, style/conventions, and security/sensitive data (secrets, `.env`).
- The supervising agent should **synthesize** findings: must-fix vs nice-to-have.
- **Block** the rest of the workflow if there are **must-fix** issues (bugs, broken imports, likely regressions, committed secrets). Fix them or ask the user before proceeding.

## 3. Automated checks

Run whatever applies in this repo (skip missing tools gracefully):

- `uv run python -m compileall -q src packages` — syntax check for packaged code.
- If `pytest`, `ruff`, or other checks exist in `pyproject.toml` or CI configs, run those too.

If any command **fails**, **do not** commit or push; report the failure and stop.

## 4. Commit (only if review + checks are clean)

- Stage intentional changes only (`git add` relevant paths; **never** `git add` secrets or unintended files).
- Write a **clear, conventional** commit message (imperative subject, body if needed).
- `git commit` (requires git write permission).

## 5. Push (only after a successful commit)

- `git push` to the **current branch** (requires network + git permissions).
- **Do not** `--force` push to `main` / `master`.
- If push fails (e.g. non-fast-forward), **do not** force; report and let the user reconcile.

## 6. Summary for the user

- What was reviewed, check results, commit hash or message, and push outcome—or why the workflow stopped early.
