# Demo runbook — Coastline College Accessibility Hub

The morning demo tells one story in about ten minutes: **Add material →
Review → Improve → Check again**, with the product being honest at every step
about what it did check, what it could not check, and what changed. Nothing in
this script claims a pass, score, or certification — because the product never
produces one.

## 1. Sixty-second setup

From the repository root, in two terminals:

**Terminal A — public site** (landing + sample walkthrough):

```sh
python3.11 -m http.server 8000
```

**Terminal B — private staging workspace:**

```sh
scripts/demo_up.sh
```

`demo_up.sh` prints the login URL (`http://127.0.0.1:8787/login` by default)
and a generated access code — keep that terminal visible or copy the code.
Set `HUB_PORT` to use another port (the service honors `PORT` first, then
`HUB_PORT`, default `8787`).

For a clean workspace with no leftover rehearsal records, delete the local
staging data first: `rm -rf .hub-staging`.

Open two browser tabs before starting:

1. `http://127.0.0.1:8000/` (landing)
2. `http://127.0.0.1:8787/login` (staging — do not sign in yet)

## 2. The storyline (~10 minutes)

### Beat 1 — Landing (1 min)

Open `http://127.0.0.1:8000/`.

> **Say:** "This is the Accessibility Hub — a reviewer for course materials
> built for educators, not auditors. One loop: add material, review, improve,
> check again. It shows evidence, not grades."

Point at the four-step journey on the page, then click **View sample review**.

### Beat 2 — Sample walkthrough (1.5 min)

You are on `sample-review.html` — a fixed illustration of one review of a
synthetic handout, not a live workspace.

> **Say:** "Every detail lands in one of four lanes: *Needs attention* — the
> machine found a concrete barrier; *Review recommended* — a person should
> look; *Verified signal* — machine evidence that something is in place; and
> *Not assessed* — things this tool honestly does not check. There is no
> overall score anywhere, on purpose."

Scroll through the lanes and the fix-and-recheck section, then switch tabs.

### Beat 3 — Staging login (0.5 min)

On the login tab, enter the access code from Terminal B.

> **Say:** "This private workspace is access-code gated and reviews only
> bundled synthetic documents — there is deliberately no upload route while
> the institutional storage and security controls are still being decided."

### Beat 4 — Review a course handout (2 min)

Click **Review a course handout**. The document page refreshes on its own
while the queued assessment runs (a few seconds).

When signals appear, walk the lanes top to bottom:

> **Say:** "The review found the handout has no document title and no primary
> language — those are *Needs attention*: concrete, machine-verifiable
> barriers. Below them, *Review recommended* items need a human eye. And
> notice *Not assessed*: contrast, tables, forms, color-only meaning. The tool
> gathers no evidence about those, so it says so instead of staying quiet.
> That honesty is the product."

If a **Review completeness** strip appears at the bottom, open it:

> **Say:** "Checks that couldn't run in this environment are disclosed here —
> the review never presents a partial check as a full one."

### Beat 5 — Improve: title and language (1.5 min)

In the **Fix Lab** panel, open **Update title and language**. Keep the
suggested values ("Week 3 Course Handout", "en-US") and click **Apply and
recheck**.

> **Say:** "The fix is applied to a copy — the original record stays intact —
> and the copy is immediately re-reviewed. We never mark our own homework
> without checking it."

### Beat 6 — Check again: the flip (1 min)

The rechecked version's page refreshes while its assessment runs. When it
settles, point at the lanes:

> **Say:** "Title and language have moved from *Needs attention* to *Verified
> signal* — each one is a separate piece of machine evidence. Two barriers are
> gone. The document doesn't get a badge for it, and the remaining lanes are
> unchanged — exactly as it should be."

### Beat 7 — Change history and provenance (1 min)

On the rechecked document page, open **4 · Check again — remediation
provenance**.

> **Say:** "Every change is recorded: what kind of repair, when, and the
> before-and-after fingerprints of the file. Each recheck is a new version;
> the source record is never rewritten."

### Beat 8 — Scanned handout and OCR (1.5 min)

Return to the **Workspace** and click **Review a scanned handout**. When
signals appear:

> **Say:** "This one is a scan — pictures of words. The review says no page
> has extractable text, which means a screen reader gets nothing."

In the Fix Lab, open **Add a text layer from this scan**, tick the
confirmation checkbox, and click **Apply text layer and recheck**.

> **Say:** "The recognized text is machine-generated, so the product requires
> a human to confirm they will review it against the page images — the
> checkbox is a real commitment, not decoration. On recheck, the extractable
> text signal is resolved; the scan image itself is untouched."

(This beat needs tesseract installed on the demo machine — verify it in the
pre-demo checklist. If it is unavailable, say the OCR path is disclosed as
unavailable rather than faked, and skip the apply.)

### Beat 9 — Remove records (0.5 min)

On a document page, open **Remove this synthetic record**, tick the
confirmation, and click **Remove records**.

> **Say:** "Synthetic records are disposable, and removal is explicit and
> audited."

### Beat 10 — Sign out (0.5 min)

Click **Sign out** in the header. You land back on the login page with "You
are signed out."

> **Close:** "Add material, review, improve, check again — with evidence at
> every step and honesty about the limits. What you never saw today: an
> overall score, a compliance claim, or a certification. That's deliberate."

## 3. Render deploy path (summary)

Full owner runbook: [private-staging-service.md](private-staging-service.md).

1. Render dashboard → **New** → **Blueprint** → select this repository. Render
   reads `render.yaml` and shows one web service, `accessibility-hub-staging`.
2. Set exactly three environment variables when prompted (leave the six
   control-reference placeholders empty):
   - `HUB_STAGING_ACCESS_CODE` — a long random code; treat it as a secret.
   - `HUB_SESSION_SECRET` — at least 32 characters of random material
     (e.g. `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`).
     Login stays closed if it is shorter.
   - `HUB_ALLOW_HOSTED_SYNTHETIC` — the exact lowercase value `true`
     (`1`, `TRUE`, and `yes` do not count).
3. Apply, wait for **Live**, then check
   `https://<your-service>.onrender.com/healthz` shows
   `"login_ready": true` and `"hosted_synthetic_optin": true`.
4. Smoke-test the hosted service before trusting it in front of anyone:

   ```sh
   python3.11 scripts/staging_smoke.py \
       --base-url https://<your-service>.onrender.com \
       --access-code "$HUB_STAGING_ACCESS_CODE"
   ```

Note: the hosted runtime installs Python packages only — no qpdf, veraPDF, or
tesseract. Hosted reviews complete and disclose those skipped checks under
*Review completeness*; the smoke test reports the OCR path as SKIP there, not
a failure.

## 4. Pre-demo checklist

Run through this the night before *and* the morning of:

- [ ] `python3.11 -m pytest tests/ -q` — full suite green.
- [ ] `rm -rf .hub-staging` — clean workspace, no rehearsal records.
- [ ] Start the demo exactly as in section 1, then run the smoke test against
      it and expect exit code 0:
      `python3.11 scripts/staging_smoke.py --base-url http://127.0.0.1:8787
      --access-code "<printed code>"`
- [ ] `tesseract --version` works on the demo machine (Beat 8); if not,
      decide now to narrate the OCR decline instead.
- [ ] Hard-refresh both browser tabs (Ctrl/Cmd+Shift+R) so no stale page or
      cached CSS appears.
- [ ] Set browser zoom for the room (110–125% projects well) and check the
      signal lanes still lay out cleanly at that zoom.
- [ ] Close devtools, extra tabs, and notifications.
- [ ] Keep Terminal B visible or the access code copied — you will type it in
      Beat 3.
