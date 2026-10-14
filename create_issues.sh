#!/usr/bin/env bash
# Creates the Sharpen backlog issues with the GitHub CLI.
# Usage: ./create_issues.sh OWNER/REPO
set -euo pipefail
REPO="${1:?usage: ./create_issues.sh OWNER/REPO}"
command -v gh >/dev/null || { echo "Install the GitHub CLI first: https://cli.github.com"; exit 1; }
gh auth status >/dev/null || { echo "Run: gh auth login"; exit 1; }

# Labels (created if missing)
for l in "accessibility" "bug" "enhancement" "good first issue" "performance" "privacy" "scaling" "security" "testing"; do
  gh label create "$l" --repo "$REPO" --force >/dev/null 2>&1 || true
done

echo "Creating issue 1/12: Rate limiter and response cache are per-process, so limits m..."
gh issue create --repo "$REPO" --title 'Rate limiter and response cache are per-process, so limits multiply with workers' --label 'bug,scaling' --body-file - <<'SHARPEN_ISSUE_BODY'
## Summary
`app.py` keeps the rate-limit counters (`_hits`) and the sharpen cache (`_cache`) in process memory. The `Procfile` and `Dockerfile` run gunicorn with 2 workers, so each worker keeps its own counters and cache.

## Impact
- The effective rate limit is roughly `RATE_LIMIT_PER_MIN x workers`.
- Cache hit rate drops, so identical prompts can hit the provider more than once.
- Counters and cache reset on every restart or deploy.

## Proposal
- Add an optional `REDIS_URL`. When set, store rate-limit counters and cached results in Redis. When unset, keep today's in-memory behaviour.
- Keep the code behind a small interface (`allow(ip, weight)`, `cache_get/put`) so the backend is swappable.

## Acceptance criteria
- With Redis configured and 2+ workers, the limit is enforced across workers (add a test using a fake or fakeredis backend).
- With no `REDIS_URL`, behaviour and tests are unchanged.
- README "Scaling note" is updated.
SHARPEN_ISSUE_BODY

echo "Creating issue 2/12: Stream the rewrite instead of showing a skeleton for the who..."
gh issue create --repo "$REPO" --title 'Stream the rewrite instead of showing a skeleton for the whole wait' --label 'enhancement,performance' --body-file - <<'SHARPEN_ISSUE_BODY'
## Summary
Sharpen waits for the full model reply before showing anything. Reasoning models (Groq `gpt-oss`, Grok 4.x) can take several seconds, and the UI shows only a skeleton and a Cancel button.

## Proposal
Stream the response (server-sent events) so the rewritten prompt appears as it is generated. The model currently returns a single JSON object, which is awkward to stream, so one approach is two phases:
1. Stream the rewritten prompt as plain text.
2. Make a second, short call for the scores, gaps and changes (or parse them from a trailing JSON block).

## Open questions
- Does streaming work with JSON mode on every supported provider?
- How should the redline update while text is still arriving (diff on completion only is fine for a first version)?

## Acceptance criteria
- First visible text appears before the full response completes.
- Cancel aborts the stream and the upstream request.
- Non-streaming providers still work through a fallback path.
SHARPEN_ISSUE_BODY

echo "Creating issue 3/12: Sharpen result is not announced to screen readers..."
gh issue create --repo "$REPO" --title 'Sharpen result is not announced to screen readers' --label 'bug,accessibility' --body-file - <<'SHARPEN_ISSUE_BODY'
## Summary
Only the toast has `aria-live` (`role="status"`). When a sharpen finishes, the result section, score, and any error are not announced, so a screen-reader user gets no feedback after pressing the button. The error alert has `role="alert"`, but the success path and the loading state have nothing.

## Proposal
- Add a visually hidden `aria-live="polite"` status region and announce "Sharpening your prompt", "Prompt sharpened. Score 79 out of 100", and "Adjustment applied: Shorter".
- Move focus to the result heading (or announce it) after a successful run.
- Confirm the Recent dialog traps and restores focus.

## Acceptance criteria
- Verified with VoiceOver and NVDA that start, success, and failure are announced once each.
- No double announcements from the toast.
- Run an axe audit and fix any serious or critical findings (add the audit to CI if practical).
SHARPEN_ISSUE_BODY

echo "Creating issue 4/12: Refining from an earlier version silently discards the later..."
gh issue create --repo "$REPO" --title 'Refining from an earlier version silently discards the later versions' --label 'bug' --body-file - <<'SHARPEN_ISSUE_BODY'
## Summary
In `refine()`, `state.versions = state.versions.slice(0, state.v + 1)` runs before the new version is pushed. If you switch to v1 and click an Adjust chip, versions v2, v3 and so on are deleted without warning.

## Steps to reproduce
1. Sharpen a prompt, then click **Shorter** (v2) and **Friendlier** (v3).
2. Click the **v1** pill.
3. Click **Simpler**.

**Expected:** all earlier work is still reachable.
**Actual:** v2 and v3 are gone; the list is now v1, v2 (Simpler).

## Proposal
Keep every version and append the new one, recording which version it was derived from (a simple parent index is enough). Show that in the pill tooltip.

## Acceptance criteria
- No version is ever removed by a refinement.
- Version pills stay in creation order and the active one is marked.
- Test covers the scenario above.
SHARPEN_ISSUE_BODY

echo "Creating issue 5/12: Share links and Recent drop fills and version history..."
gh issue create --repo "$REPO" --title 'Share links and Recent drop fills and version history' --label 'enhancement' --body-file - <<'SHARPEN_ISSUE_BODY'
## Summary
A share link (and a Recent entry) stores only the current version's text, the scores, gaps and changes. It does **not** store the values filled into `[PLACEHOLDERS]` or the other versions, so reopening it shows blanks again and the version pills are gone.

## Proposal
- Include `fills` in the payload (the user can choose "Include my filled values" before copying, since they may contain personal details).
- Include the version list with labels, capped by size.
- Keep links short: compress the JSON (for example with `CompressionStream` where available) and fall back to the current format.

## Acceptance criteria
- Round trip: copy link, open in a new tab, same text, fills, versions and active version.
- Old links keep working.
- A warning is shown if the link would exceed a chosen length (for example 8 KB).
SHARPEN_ISSUE_BODY

echo "Creating issue 6/12: Placeholder detection is too narrow and can misfire on text ..."
gh issue create --repo "$REPO" --title 'Placeholder detection is too narrow and can misfire on text the user wrote' --label 'bug' --body-file - <<'SHARPEN_ISSUE_BODY'
## Summary
Placeholders are detected with `/\[([A-Z][A-Z0-9 _\/-]{1,40})\]/g`. That means:
- Models that write `{{audience}}`, `<AUDIENCE>` or `[audience]` get no fill-in form.
- A bracketed uppercase phrase the user wrote on purpose (for example `[TODO]` or `[IMPORTANT]`) is treated as a blank to fill.
- Names longer than 41 characters or starting with a digit are ignored.

## Proposal
- Have the model return its placeholders explicitly (a `placeholders` array in the JSON), and only treat those as blanks.
- Keep the regex as a fallback for older results and shared links.
- Ignore bracketed text that appeared in the user's original prompt.

## Acceptance criteria
- Blanks are exactly the ones the rewrite introduced.
- Tests cover `[TODO]` in the original prompt and a placeholder with digits.
SHARPEN_ISSUE_BODY

echo "Creating issue 7/12: Redline is noisy when the rewrite reorders or rephrases the ..."
gh issue create --repo "$REPO" --title 'Redline is noisy when the rewrite reorders or rephrases the original' --label 'enhancement' --body-file - <<'SHARPEN_ISSUE_BODY'
## Summary
The redline is a word-level longest-common-subsequence diff. It works well when the original words survive in order, but when the model rephrases or moves them, the view fills with scattered struck-through words and tiny insertions that are hard to read.

## Proposal
- Add a toggle: **Words** (current) and **Sentences/lines**, where whole lines are marked as kept, added or removed.
- Merge small gaps: if two changes are separated by only one or two unchanged words, show them as one change.
- Optional: a summary line, for example "Kept 9 of your 12 words".

## Acceptance criteria
- Toggle persists in the session.
- A fixture with heavily reworded text produces a readable result (add a snapshot test of the diff operations).
- Performance: still instant for 4,000-character prompts.
SHARPEN_ISSUE_BODY

echo "Creating issue 8/12: Optional access control for public deployments..."
gh issue create --repo "$REPO" --title 'Optional access control for public deployments' --label 'enhancement,security' --body-file - <<'SHARPEN_ISSUE_BODY'
## Summary
Anyone who can reach a deployed instance can spend the owner's model credits. Rate limiting slows this down but cannot stop a determined user, and `/api/status` publicly reports the provider and model.

## Proposal
- Add optional `APP_PASSWORD` (or `ACCESS_TOKEN`). When set, the API requires it (basic auth or a bearer token) and the UI prompts once and remembers it for the session.
- Add `STATUS_PUBLIC=0` to return only `{ok: true}` from `/api/status`.
- Document recommended setups: private network, reverse-proxy auth, or this token.

## Acceptance criteria
- With the token set, every `/api/*` route except a minimal health check returns 401 without it.
- Constant-time comparison is used.
- With no token configured, behaviour is unchanged.
SHARPEN_ISSUE_BODY

echo "Creating issue 9/12: Let users turn off saving Recent prompts..."
gh issue create --repo "$REPO" --title 'Let users turn off saving Recent prompts' --label 'enhancement,privacy' --body-file - <<'SHARPEN_ISSUE_BODY'
## Summary
Every sharpened prompt, including the rewrite, is saved to `localStorage` (last 12) with no way to opt out. People paste confidential text into prompt tools, and shared computers will keep it.

## Proposal
- Add a "Save recent prompts on this device" switch (default on, remembered).
- When switched off, clear existing history after confirming.
- Mention in the footer that history is local and can be disabled.

## Acceptance criteria
- With the switch off, nothing is written to `localStorage` for prompts or results.
- Clear history still works.
- Test covers both states.
SHARPEN_ISSUE_BODY

echo "Creating issue 10/12: Add browser end-to-end tests to CI..."
gh issue create --repo "$REPO" --title 'Add browser end-to-end tests to CI' --label 'testing,good first issue' --body-file - <<'SHARPEN_ISSUE_BODY'
## Summary
The 31 tests cover the Python code only. The front end (redline diff, placeholder form, versions, share-link round trip, XSS safety, history) has no tests in the repository and CI never opens a browser.

## Proposal
Add a Playwright test suite that starts the app with `DEMO_MODE=1` (no key needed) and mocks the model for the XSS and error cases. First cases:
- Sharpen, fill a blank, switch tabs with the keyboard.
- Refine creates a second version and the pills switch between them.
- Share link round trip restores the result.
- Model text such as `<img src=x onerror=...>` renders as text.
- A failed request restores the previous result and shows the error.
- No horizontal scroll at 390 px wide.

## Acceptance criteria
- `npm`/`pip` setup documented in the README Development section.
- A separate CI job runs it on every push and uploads screenshots on failure.
SHARPEN_ISSUE_BODY

echo "Creating issue 11/12: Show the Ctrl/Cmd+Enter shortcut in the UI..."
gh issue create --repo "$REPO" --title 'Show the Ctrl/Cmd+Enter shortcut in the UI' --label 'enhancement,good first issue' --body-file - <<'SHARPEN_ISSUE_BODY'
## Summary
Pressing Ctrl or Cmd + Enter in the prompt box sharpens it, but nothing in the interface says so, and the README does not mention it.

## Proposal
Add a small hint next to the character count (for example "Ctrl+Enter to sharpen", showing Cmd on macOS), and mention it in the README Features table.

## Acceptance criteria
- The hint appears on desktop and is hidden on touch-only devices.
- Text meets contrast requirements in light and dark themes.
SHARPEN_ISSUE_BODY

echo "Creating issue 12/12: Check at startup that the configured model still exists..."
gh issue create --repo "$REPO" --title 'Check at startup that the configured model still exists' --label 'enhancement' --body-file - <<'SHARPEN_ISSUE_BODY'
## Summary
Provider lineups change (Groq retired Llama 3.3 70B on 2026-08-16). Sharpen falls back to the next model at request time and logs a warning, but an operator only finds out when someone reads the logs, and the stale `LLM_MODEL` stays in `.env` indefinitely.

## Proposal
- On startup (and in a `/healthz` check), call the provider's `GET /models` where available and warn clearly if `LLM_MODEL` is missing: "LLM_MODEL=... is not available; using ...".
- Expose the result as `model_ok` in `/healthz` so uptime monitors can alert.
- Never block startup on a failed lookup.

## Acceptance criteria
- Unit test with a mocked `/models` response (present, missing, request fails).
- Works for Groq and xAI; skipped quietly for providers without `/models`.
SHARPEN_ISSUE_BODY

echo "Done."