# Accessibility Hub agent operations

Start with `docs/agent-devops.md` and `scripts/dev_preflight.sh`. Work from a clean, isolated branch based on the current `origin/main`; preserve other checkouts, uncommitted work, running services, and Docker volumes. The named Claude branches are feature branches, not deployment targets.

For code changes, run the relevant focused tests, then the repository's full Python suite and Docker smoke test when their prerequisites are present. Report skipped checks and the exact missing prerequisite. Keep real-document intake closed; do not turn on hosted intake, public access, or model egress.

Do not push, merge, deploy, change Render settings, create cloud resources or credentials, or run a production rollback without explicit approval for that action. `render.yaml` has `autoDeploy: true`, so a push to `main` can deploy staging. Keep the locked `render.real-intake.yaml` separate.
