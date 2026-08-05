# Demo runbook — Coastline College Accessibility Hub

The demo now tells the story in two acts. The **opening act** is the teacher
happy path in three simple steps — sign in and drop a PDF, watch one
processing screen do the improving for you, download the ready copy with its
insight cards. Four interactions, zero decisions. The **deep-dive act** is the
original ten-minute walkthrough of every lane, repair, and disclosure. Both
acts stay honest at every step about what the product did check, what it could
not check, and what changed. Nothing in this script claims a pass, score, or
certification — because the product never produces one.

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

## 2. Opening act — three simple steps (~3 minutes)

Development mode only (`scripts/demo_up.sh` runs it). Hosted staging keeps
the access-code form and refuses uploads exactly as before — this whole act
does not exist there. Bring one of your own PDFs, or make one on the spot;
the flow is most convincing on a file the room has never seen. The whole act
is **four interactions**: the sign-in click, choosing the file, one button,
and the download.

### Step 1 — Land and drop (0.5 min)

Open `http://127.0.0.1:8787/login`. Above the access-code form there is one
button: **Sign in with your Coastline Microsoft account**, with the caption
"Demo sign-in — no Microsoft account is contacted."

> **Say:** "One honest stub: this button only plays the part of campus SSO.
> Nothing leaves this machine."

Click it. You land directly on one centered card — eyebrow **Three simple
steps**, headline **"Make your course material ready for students."**, and
the lead "Drop in a PDF (up to 50 MB). We review it, apply safe improvements
to a copy, and hand back a version that is ready to share." The sidebar is
just the logo, the persona card (**Jordan Rivera, Faculty** — "Signed in"),
and **Sign out** — no menus, no decisions.

The **Course material (PDF)** input now sits inside a dashed drop zone with
a coral document glyph and the hint "Drag your PDF here, or choose a file
above." Drag a file over it and the zone lights up coral — drop it, or pick
it with the input, and the hint flips to **"Ready to transform:
&lt;your file&gt;.pdf"** on a green zone. Then click **Transform my
document →**. (If you have transformed documents before, a quiet **Recent**
list sits under the card; the tiny footer reads "No file handy? **Try a
sample document.**" and runs the same three steps on a bundled sample.)

### Step 2 — One processing screen does the improving (1 min)

You are on **Step 2 of 3**, and the document takes its journey. Above the
status, a little night-sky scene: your document — a coral tile with a page
icon — flies a dashed track between three stops (page icon → spark icon →
check mark) while stars twinkle and the odd comet streaks past. The
headline moves with the real work — **"Reading your document…"**,
**"Applying safe improvements…"**, **"Verifying the new copy…"** — and as
each stage completes, its tile flips green and a small burst of sparks
trails off the traveling document: **Reading your document** ("A careful
automatic review"), **Applying safe improvements** ("Only a copy is ever
changed"), **Verifying the new copy** ("A fresh review of the result"). The
page notes "This page updates by itself every few seconds" — the teacher
never clicks. (One first-party script, `/assets/journey.js`, drives the
polling and the scene; with JavaScript off the page falls back to its plain
5-second refresh and the same stage tiles, and under reduced-motion
settings the whole scene stands perfectly still.)

Behind the screen the pipeline assesses the file, and if the title or
primary language is missing it applies that fix **on a copy** (title from
the filename, language English (US)) with the same full provenance record
as the manual Fix Lab path, then re-reviews the improved copy. Nothing else
is ever changed automatically.

Below the progress card, the clearly labeled **Sponsored** card glides in
from the right — brought to you by our sponsors, ending with the line
"Sponsor messages never delay your results." It is server-rendered and
first-party, and it is gone the moment the document is ready.

> **Say:** "The sponsor card is server-rendered, first-party, labeled, and
> gone the moment your document is ready. It never gates anything."

### Step 3 — Ready (1.5 min)

The page carries you forward by itself to **Step 3 of 3 — "Your document is
ready."** The arrival celebrates once: a brief confetti fall in the brand
colors, the coral seal badge pops into place, and a corner of small stars
keeps twinkling — then everything settles to calm. (Under reduced motion
there is no burst and no pop; the page simply arrives.) One big button:
**Download your document ↓**. Under it, the coral badge — **Reviewed &
improved / Coastline College Accessibility Hub**, the date, a short
evidence hash — and the line **"A review record, not a certification."**

Walk the insight cards, top to bottom:

- **What we improved** — green cards naming exactly what was set, e.g.
  **"Title added** — Screen readers now announce 'Week 5 Handout' instead of
  a filename." and **"Language set to English (US)"**, with the note
  "Improvements were applied to a copy. Your original file is untouched."
  (This section only appears if something was actually fixed.)
- **Worth a human look** — the review-recommended findings in plain
  language, e.g. **Tags and reading order**, **Image descriptions**,
  **Link purpose**.
- **Verified in your document** — compact chips, e.g. **Document title**,
  **Primary language**.
- **Not checked by this tool** — one honest strip: "Visual contrast · Table
  structure semantics · Form field labels · Color-only meaning. These are
  judgment calls this tool leaves to a person." plus any checks that could
  not run in this environment.

Click **Download your document ↓**. The file arrives as `<name>.ready.pdf` —
the improved copy with exactly one added "Review summary" page carrying the
seal wording, the review date, the evidence hash, where findings landed, and
the fixes applied.

> **Say:** "This is a review record you can attach to the file — not a
> badge, not a certification. Every other page is exactly what you uploaded,
> plus the title and language set on a copy."

Point at the closing row — **Transform another document →** loops back to
the drop page; the quiet **Advanced tools** link opens the full classic
document page (lanes, Fix Lab, structure, OCR) for power users. Click
**Sign out**. That is the whole teacher loop: drop, wait, download.

## 3. Deep-dive act — the storyline (~10 minutes)

### Beat 1 — Landing (1 min)

Open `http://127.0.0.1:8000/`.

> **Say:** "This is the Accessibility Hub — a reviewer for course materials
> built for educators, not auditors. One loop: review, understand, improve,
> verify. It shows evidence, not grades."

Point at the four-step model on the page (Review → Understand → Improve →
Verify), then find the **Try a guided sample** card and click its
**Start guided sample** button (the card heading itself is not a link; a
second Start guided sample button near the bottom of the page works too).

### Beat 2 — Guided sample (1.5 min)

You are on `sample-review.html` — an interactive walkthrough of one synthetic
review. The four findings are real toggle buttons: click one (or use the
keyboard) and the panel beside them reveals its evidence, student impact, next
action, and verification step. A separate **Verified signal** strip and the
**Improve/Verify** beats below show the fix-on-a-copy story.

> **Say:** "Every detail lands in one of four lanes: *Needs attention* — the
> machine found a concrete barrier; *Review recommended* — a person should
> look; *Verified signal* — machine evidence that something is in place; and
> *Not assessed* — things this tool honestly does not check. There is no
> overall score anywhere, on purpose."

Click through a finding or two, scroll past the Verified signal strip and the
Improve/Verify beats, then switch tabs.

### Beat 3 — Staging login (0.5 min)

On the login tab, enter the access code from Terminal B. (If you just
finished the opening act, click **Sign out** first — the deep-dive uses the
access-code session on purpose.)

> **Say:** "This access-code session is the one the hosted service gets: it
> reviews only bundled synthetic documents, and there is deliberately no
> upload route while the institutional storage and security controls are
> still being decided. The upload you saw a minute ago exists only for the
> local demo educator sign-in."

### Beat 4 — Review a course handout (2 min)

Click **Start a sample review**. A progress page checks again every five
seconds while the queued assessment runs (usually just a few).

When signals appear, walk the lanes top to bottom:

> **Say:** "The review found the handout has no document title and no primary
> language — those are *Needs attention*: concrete, machine-verifiable
> barriers. Below them, the *Review recommended* item needs a human eye. And
> notice *Not assessed*: contrast, tables, forms, color-only meaning. The tool
> gathers no evidence about those, so it says so instead of staying quiet.
> That honesty is the product."

Open the **Review completeness** strip at the bottom (expect it on a demo
laptop — the deeper structure and full-standard validators are usually not
installed, and the review discloses exactly that):

> **Say:** "Checks that couldn't run in this environment are disclosed here —
> the review never presents a partial check as a full one."

### Beat 5 — Improve: title and language (1.5 min)

In the **Fix the clearest issues** panel (step *3 · Improve*), keep the
suggested values ("Week 3 Course Handout", "en-US") and click **Apply and
recheck**.

> **Say:** "The fix is applied to a copy — the original record stays intact —
> and the copy is immediately re-reviewed. We never mark our own homework
> without checking it."

### Beat 6 — Verify: the flip (1 min)

The rechecked version's page refreshes while its assessment runs. When it
settles, a green **Your improved copy is ready** banner reports "2
accessibility signals are now verified in the recheck." Point at the lanes:

> **Say:** "Title and language have moved from *Needs attention* to *Verified
> signal* — each one is a separate piece of machine evidence. Two barriers are
> gone. The document doesn't get a badge for it, and the remaining lanes are
> unchanged — exactly as it should be."

### Beat 7 — Change history and provenance (1 min)

On the rechecked document page, open the **Remediation provenance** details
under the signals.

> **Say:** "Every change is recorded: what kind of repair, when, and the
> before-and-after fingerprints of the file. Each recheck is a new version;
> the source record is never rewritten."

### Beat 8 — Scanned handout and OCR (1.5 min)

Return to the **Workspace** and click **Try the scanned sample**. When
signals appear:

> **Say:** "This one is a scan — pictures of words. The review says no page
> has extractable text, which means a screen reader gets nothing."

In the Fix Lab panel, open **Add a text layer from this scan**, tick the
confirmation checkbox, and click **Apply text layer and recheck**.

> **Say:** "The recognized text is machine-generated, so the product requires
> a human to confirm they will review it against the page images — the
> checkbox is a real commitment, not decoration. On recheck, the extractable
> text card is gone from the lanes — resolved — and the scan image itself is
> untouched."

The green banner on this recheck reads "Compare the lanes with the previous
version to see what changed" — point at the lanes (the Extractable text card
has disappeared), not at a verified count; unlike Beat 6, this repair resolves
a signal without minting a new verified one.

(This beat needs tesseract installed on the demo machine — verify it in the
pre-demo checklist. If it is unavailable, say the OCR path is disclosed as
unavailable rather than faked, and skip the apply.)

### Beat 9 — Remove records (0.5 min)

On a document page, open **Remove this synthetic record**, tick the
confirmation, and click **Remove records**.

> **Say:** "Synthetic records are disposable, and removal is explicit and
> audited."

Removal covers the version you are on and its rechecked copies; other
lineages you created earlier stay listed in the workspace, so don't promise
an empty list unless you remove each one.

### Beat 10 — Sign out (0.5 min)

Click **Sign out** in the sidebar. You land back on the login page with
"You are signed out."

> **Close:** "Review, understand, improve, verify — with evidence at
> every step and honesty about the limits. What you never saw today: an
> overall score, a compliance claim, or a certification. That's deliberate."

## 4. Render deploy path (summary)

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

## 5. Pre-demo checklist

Run through this the night before *and* the morning of:

- [ ] `python3.11 -m pytest tests/ -q` — full suite green.
- [ ] `python3.11 scripts/make_test_corpus.py && python3.11
      scripts/transform_bench.py corpus --fast` — exit 0: every corpus document
      transforms or declines for a stated reason. Open
      `bench-out/bench-report.html` if any row surprises you.
- [ ] `rm -rf .hub-staging` — clean workspace, no rehearsal records.
- [ ] Start the demo exactly as in section 1, then run the smoke test against
      it and expect exit code 0:
      `python3.11 scripts/staging_smoke.py --base-url http://127.0.0.1:8787
      --access-code "<printed code>"`
- [ ] Have a real PDF ready for the opening act (any course handout under
      50 MB); rehearse the three steps once so the sponsored card and the
      `.ready.pdf` download hold no surprises.
- [ ] `tesseract --version` works on the demo machine (Beat 8); if not,
      decide now to narrate the OCR decline instead.
- [ ] If you plan to click **Open local reviewer** on the landing page, start
      the workbench on its default port first: `python3.11 local_reviewer.py`
      (the landing link points at `http://127.0.0.1:8765/` — a custom `--port`
      makes that link a dead end on stage).
- [ ] Hard-refresh both browser tabs (Ctrl/Cmd+Shift+R) so no stale page or
      cached CSS appears.
- [ ] Set browser zoom for the room (110–125% projects well) and check the
      signal lanes still lay out cleanly at that zoom.
- [ ] Close devtools, extra tabs, and notifications.
- [ ] Keep Terminal B visible or the access code copied — you will type it in
      Beat 3.
