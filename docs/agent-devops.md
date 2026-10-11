# Agent DevOps workflow

This is the local operating procedure for the Accessibility Hub repository. `main` is the default repository branch and the CI push branch. Confirm the actual branch of any existing Render service before deployment. The synthetic staging service and the locked real-intake Blueprint are separate. Follow `AGENTS.md` for action boundaries.

## Safe update and validation

1. Run `scripts/dev_preflight.sh`. If the tree is dirty, preserve it and use another worktree or clone. Never overwrite another agent's checkout.
2. In a clean checkout, run `git fetch origin`, inspect `git log --oneline --decorate -5 origin/main`, and use `git pull --ff-only origin main` only when on local `main`. For changes, branch from `origin/main`; use a PR to propose them. Record `git rev-parse HEAD` for every test/deploy report.
3. Create `.venv` with `python3.11 -m venv .venv` and install the pinned dependencies with `.venv/bin/python -m pip install -r requirements-real-intake.txt`. On macOS, the Python wheels alone are insufficient for WeasyPrint: install its native Pango/GObject libraries according to the official WeasyPrint macOS guide. The full reading-order test also needs Poppler's `pdftotext`. `scripts/dev_preflight.sh` shows whether those tools are available.
4. Run `.venv/bin/python -m unittest discover -s tests -v`. CI also compiles Python modules, runs the PostgreSQL schema security contract, and builds and smoke-tests the Docker image. Use `.github/workflows/test.yml` and `docker.yml` as the exact CI recipe. A missing native tool or database is a blocked check, not a passing check.
5. For the PR #19 reading-order fix, run `.venv/bin/python -m unittest tests.test_layout -v` with Poppler and WeasyPrint available. It checks complete paragraphs, wrapped URL links, an image between text blocks, form block numbering, and fallback extraction.

## Local demo

Prefer `scripts/demo_docker.sh --rebuild` when Docker is installed and available. It builds the full toolchain and starts the development demo on `127.0.0.1:8787/login`, with a persistent local `hub-demo-data` volume. Inspect the script before use. The flag belongs to this script; `git pull scripts/demo_docker.sh --rebuild` is not a valid update command. Avoid starting a second `hub-demo` container or replacing a running one.

Without Docker, use `PYTHON="$PWD/.venv/bin/python" scripts/demo_up.sh`. It generates a local access code and secret and starts the synthetic workbench. The native path may skip PdfCraft, veraPDF, qpdf, OCR, and Poppler checks; the product reports these under Review completeness. Open the URL printed by the script. Do not put a generated access code in tickets or logs shared outside this computer.

In another terminal, set `HUB_STAGING_ACCESS_CODE` to the code printed by the active demo, then run `.venv/bin/python scripts/staging_smoke.py --base-url http://127.0.0.1:8787 --access-code "$HUB_STAGING_ACCESS_CODE"`. The smoke test covers `/healthz`, sign-in, a synthetic review and repair, history, and the no-upload boundary. Check `/healthz` for the current toolchain and confirm `hosted_intake_enabled` is false. Stop only the demo you started; preserve other running work and the Docker volume.

## Hosted staging and release gate

`render.yaml` declares a paid Starter Docker service with a persistent disk, `/healthz`, and `autoDeploy: true`. Its access/session secrets and hosted synthetic opt-in are dashboard managed. This file is a declaration, not proof a service exists. Before any deployment, an authorized owner must identify the actual Render service, account, branch, cost, env configuration, disk/backup policy, and current deployed commit. No agent should infer deploy authority from local Git access.

For an approved staging release, record the predeploy commit, review CI status for the candidate commit, confirm the hosted synthetic and real-intake boundaries, then deploy through the owner's approved route. Confirm Render reports Live, check `/healthz`, and run `scripts/staging_smoke.py` against the approved staging URL with its access code. Record the deployed commit, test results, and Render log window; inspect logs for startup, worker, storage, and repeated request failures. Do not write secrets or document content into the report.

If a deployment is bad, stop further rollout and notify the owner. Preserve the disk and logs. The authorized operator can use Render's deployment history to redeploy the last known good image/commit, then repeat `/healthz` and the staging smoke test. Do not delete a disk or automatically roll back: schema and stored-record compatibility must be checked first. The separate `render.real-intake.yaml` has deployment off and must stay locked.

## Operating limits

The local agent can inspect, branch, edit, test, build, and report while this Mac is on. An IDE window or local process does not provide unattended operation when the Mac is off. Continuous hosted operation needs an approved hosting choice, bounded Git/Render permissions, credentials configured by the owner, and a decision on who may trigger deploys and rollbacks. Do not create those resources or grant access as part of local setup.
