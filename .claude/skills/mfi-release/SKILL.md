---
name: mfi-release
description: Pre-flight checklist and ordered ship sequence for releasing a new Medicaid Inspector version. Trigger when the user says "ship v<x.y.z>", "release v<x.y.z>", "deploy v<x.y.z>", "cut a release", or any variation that implies bumping the version and pushing both backend and frontend to production. Also trigger when the user asks "what's left before I can ship?" or "is this branch ready to release?"
---

# Medicaid Inspector — Release Skill

You are coordinating a production release of the Medicaid Inspector app. Every step is human-gated — pause for confirmation before any irreversible action. Use the `mfi` CLI (at repo root) wherever possible; only fall back to raw `gcloud` / `firebase` / `npm` when the CLI does not cover the step.

## Inputs you need first

If any of these are missing, ask before proceeding:

1. **Target version** (e.g. `3.0.13`) — must follow semver. Patch bumps are the default per project convention (one patch bump per session).
2. **Scope** — `frontend only`, `backend only`, or `both`. Default: `both`.
3. **Smoke-test plan** — which screens / endpoints will be hit post-deploy. Default: `/health` for backend, `/` + bundle version check for frontend.

## The ordered checklist

Work top to bottom. Mark each step done in a TaskList. Do NOT skip ahead.

### 1. Pre-flight (read-only)

- [ ] `git status` — confirm clean working tree (or only intended uncommitted changes).
- [ ] `git fetch origin && git log HEAD..origin/main` — confirm not behind remote, or plan a rebase.
- [ ] `cat frontend/package.json | grep version` — record current version.
- [ ] Run `./mfi version` to confirm CLI sees the current version.
- [ ] If the user named a target version, verify it's a strict increment over current.

### 2. Version bump

- [ ] Edit `frontend/package.json` only — that is the canonical version source. Vite injects it as `__APP_VERSION__`.
- [ ] Do NOT touch backend version strings; backend version follows frontend.

### 3. Build

- [ ] If scope includes frontend: run `cd frontend && npm run build` and confirm exit 0.
- [ ] Inspect bundle size warning (>500KB warning is expected — only flag if size grew significantly).
- [ ] If scope includes backend only: skip this section.

### 4. Commit

- [ ] Stage ONLY intended files. Never `git add -A` or `git add .` — the repo has untracked secrets (`firebase-sa-key.json`), runtime logs, and JSON state files that must stay untracked.
- [ ] Commit message format:
      ```
      v<x.y.z>: <one-line summary>

      <bulleted backend changes>
      <bulleted frontend changes>
      ```
- [ ] Include the standard `Co-Authored-By: Claude …` trailer.

### 5. Reconcile with origin

- [ ] `git pull --rebase origin main` — rebase local commits onto origin to avoid criss-cross merges. This repo has had divergence issues from GitHub auto-PR merges before.
- [ ] If conflicts: stop, surface them to the user, do not resolve unilaterally.

### 6. Push

- [ ] `git push origin main`.
- [ ] If the push is rejected, do NOT use `--force` or `--force-with-lease` without explicit user approval.

### 7. Deploy

- [ ] If scope includes backend: `./mfi deploy backend`. CLI runs `gcloud run deploy` and smoke-tests `/health` automatically.
- [ ] If scope includes frontend: `./mfi deploy frontend`. CLI runs `npm run build` (unless `--skip-build`), `firebase deploy --only hosting`, and verifies the deployed bundle contains the declared version.

### 8. Verify

- [ ] Backend: `curl -s -o /dev/null -w "%{http_code}" $MFI_BACKEND_URL/health` returns `200`.
- [ ] Frontend: fetch `https://medicaid-inspector.web.app/` and confirm the bundle hash matches what was just built; fetch the bundle and confirm `"<x.y.z>"` is present.
- [ ] If verification fails, do NOT mark the release done. Report the discrepancy to the user.

### 9. Post-flight

- [ ] (Optional, only if user asks) tag: `git tag v<x.y.z> && git push origin v<x.y.z>`.
- [ ] Summarize: version, commit SHA, Cloud Run revision id, Firebase hosting URL, bundle hash. One concise table.

## Anti-patterns — do not do these

- **Do not** create commits without the user's explicit ship instruction.
- **Do not** `git push --force` to main without explicit approval, and never to a release tag.
- **Do not** skip the post-deploy verify step. A deploy that "succeeded" without verification is unconfirmed.
- **Do not** stage untracked JSON state files, log files, or anything in `deploy-tmp/` or `backend/.tmp/`. The `.gcloudignore` and `.gitignore` exist for a reason.
- **Do not** amend the previous commit if a pre-commit hook fails — fix the issue and make a NEW commit.
- **Do not** skip hooks (`--no-verify`) without explicit user approval.

## Output template for the user

Once the release lands, post this exact format:

```
Shipped v<x.y.z>

| Step | Result |
|------|--------|
| Commit       | <SHA> |
| Push         | <SHA> -> origin/main |
| Backend      | Cloud Run revision <revision-id> (health: 200) |
| Frontend     | Firebase hosting (bundle: assets/index-<hash>.js, verified v<x.y.z>) |
| Tag          | v<x.y.z> (or "skipped per user") |
```
