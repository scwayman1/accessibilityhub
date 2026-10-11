**DRAFT — prepared for counsel review. Not legal advice. Not yet adopted.**

# Coastline Accessibility Hub — Accessibility Conformance Report (draft)

**Based on VPAT® Version 2.5 — WCAG 2.2 edition (format adapted; not an ITI-issued document)**

| Field | Value |
|---|---|
| Name of product / version | Coastline Accessibility Hub, repository revision [COMMIT SHA] |
| Report date | [2026-10-11] (draft) |
| Product description | Educator-facing PDF accessibility review tool: deterministic findings in four lanes, teaching cards, permission-gated fixes on a copy, recheck |
| Contact | [ACCESSIBILITY CONTACT NAME / EMAIL] |
| Notes | This report covers the **product's own user interface**. It says nothing about the conformance of documents users review or produce with the product. |

## Evaluation methods used — read first

**Formal testing with assistive technology is pending.** No screen reader (JAWS, NVDA, VoiceOver, TalkBack), voice control, screen magnifier, or manual expert audit has yet been performed on any surface. Results below come only from:

1. **Source-code inspection** of the HTML/CSS/JS on [2026-10-11].
2. **Automated design-contract tests** run in CI: `tests/test_design_contract.py` (skip links, 16px base, 14px secondary floor, reduced-motion support, step-label contrast, sponsor content never a live region, assertive errors/polite status) and `tests/test_ui_debt.py` (labeled file input, 320px layout, keyboard-reachable controls, focus moved to updated heading, accessible reorder buttons).
3. **Contrast computation** of design-token color pairs.

Conformance values marked "(code inspection)" are provisional. VPAT 2.5 guidance permits "Not Evaluated" only for Level AAA; it is used here for A/AA criteria **as an internal honesty marker** and every such entry must be replaced with a tested result before this report is published externally.

## Scope — surfaces

| Surface | Source | In scope |
|---|---|---|
| Public site | `index.html` (`landing.html` identical) | Yes |
| Guided sample review | `sample-review.html` | Yes |
| Local workbench (Fix Lab) | `local_reviewer.html` served by `local_reviewer.py` | Yes |
| Hosted workspace (staging; sign-in, review, Fix Lab, progress) | HTML generated in `service/app.py` | Yes |
| Clerk-hosted sign-in / Microsoft Entra sign-in pages | Third-party | **No** — request vendors' ACRs [OPEN ITEM] |
| Exported files (evidence receipt JSON, HTML draft, fixed PDF; planned tagged PDF/HTML output) | Generated content | **No** — evaluated per document by the product's own checks; not covered by this ACR |

## Applicable standards

| Standard | Included |
|---|---|
| WCAG 2.2 Level A | Yes (Table 1) |
| WCAG 2.2 Level AA | Yes (Table 2) |
| WCAG 2.2 Level AAA | No |
| Revised Section 508 / EN 301 549 | Not separately reported in this draft [ADD if Institution requires] |

## Terms

- **Supports** — functionality meets the criterion without known defects.
- **Partially Supports** — some functionality does not meet the criterion.
- **Does Not Support** — the majority of functionality does not meet the criterion.
- **Not Applicable** — criterion not relevant to the product.
- **Not Evaluated** — not yet assessed (see note above).

## Table 1 — WCAG 2.2 Level A

| Criterion | Conformance level | Remarks and explanations |
|---|---|---|
| 1.1.1 Non-text Content | Supports (code inspection) | Hero image has descriptive alt; logos/decorative images use alt="" or text alternative ("Coastline College"); inline SVG icons `aria-hidden`; workbench figure previews get generated alt ("Preview of figure N for you to describe"). Confirm decorative logo in `sample-review.html` header has adjacent text name. |
| 1.2.1 Audio-only and Video-only (Prerecorded) | Not Applicable | No audio or video. |
| 1.2.2 Captions (Prerecorded) | Not Applicable | No media. |
| 1.2.3 Audio Description or Media Alternative | Not Applicable | No media. |
| 1.3.1 Info and Relationships | Not Evaluated | Code shows `header`/`nav`/`main`/`footer` landmarks, heading hierarchy, labeled file input, `aria-current` on workflow steps. Needs AT verification of tables, finding lists, and generated hosted pages. |
| 1.3.2 Meaningful Sequence | Not Evaluated | Narrow layout inserts finding detail inline beneath the selected finding (test-enforced); reading order not AT-verified. |
| 1.3.3 Sensory Characteristics | Not Evaluated | — |
| 1.4.1 Use of Color | Supports (code inspection) | Lanes are always labeled in text (Needs attention, Review recommended, Verified signal, Not assessed); color is supplementary. |
| 1.4.2 Audio Control | Not Applicable | No audio. |
| 2.1.1 Keyboard | Not Evaluated | Controls are native buttons/inputs/links; sample toggles are `<button aria-pressed>`; reading-order changes use up/down buttons rather than drag. Full keyboard walk-through pending. |
| 2.1.2 No Keyboard Trap | Not Evaluated | No modal dialogs or custom focus traps observed in code. |
| 2.1.4 Character Key Shortcuts | Supports (code inspection) | No single-character shortcuts defined. |
| 2.2.1 Timing Adjustable | Partially Supports (code inspection) | Hosted staging session expires after 8 hours without a warning or extension; hosted progress page's no-JavaScript fallback uses `<meta http-equiv="refresh" content="5">` (WCAG failure technique F41). With JavaScript, status polling updates in place without reload. |
| 2.2.2 Pause, Stop, Hide | Partially Supports (code inspection) | While a review runs, decorative animations (progress sweep, pulsing orb, journey animation) and sponsor cards appear without an on-page pause control. All animations stop under the OS "reduce motion" setting (`prefers-reduced-motion`, test-enforced on every surface); sponsor content is excluded from live regions. Add an on-page pause control. |
| 2.3.1 Three Flashes or Below Threshold | Not Evaluated | Animations are slow (≥0.8 s cycles) by code; not measured. |
| 2.4.1 Bypass Blocks | Supports (code inspection) | "Skip to main content" link to `#main-content` on all four surfaces (test-enforced). |
| 2.4.2 Page Titled | Supports (code inspection) | Descriptive `<title>` on static pages and hosted pages (e.g., "Sign in — Accessibility Hub"). |
| 2.4.3 Focus Order | Not Evaluated | Selecting a finding moves focus to the updated detail heading (test-enforced); full order unverified. |
| 2.4.4 Link Purpose (In Context) | Not Evaluated | — |
| 2.5.1 Pointer Gestures | Supports (code inspection) | No multipoint or path-based gestures. |
| 2.5.2 Pointer Cancellation | Supports (code inspection) | Native click activation only. |
| 2.5.3 Label in Name | Not Evaluated | — |
| 2.5.4 Motion Actuation | Not Applicable | No motion-actuated functions. |
| 3.1.1 Language of Page | Supports (code inspection) | `lang="en"` on all surfaces. |
| 3.2.1 On Focus | Not Evaluated | — |
| 3.2.2 On Input | Not Evaluated | — |
| 3.2.6 Consistent Help | Not Evaluated | No help mechanism yet identified across pages. |
| 3.3.1 Error Identification | Supports (code inspection) | Errors rendered in text with `role="alert"`/assertive; non-PDF selection rejected with a plain-language message (test-enforced). |
| 3.3.2 Labels or Instructions | Partially Supports (code inspection) | File input and access-code field have visible labels. Workbench AI-setup and fix fields use `<label for>`. Fix Lab link-description inputs are named by `aria-label` plus placeholder text; confirm whether adjacent on-screen text serves as a persistent visible label. |
| 3.3.7 Redundant Entry | Not Evaluated | — |
| 4.1.1 Parsing | Supports | Obsolete in WCAG 2.2; treated as satisfied per W3C errata. |
| 4.1.2 Name, Role, Value | Not Evaluated | Native elements, `aria-pressed`, `aria-current`, `aria-controls` used; AT verification pending. |

## Table 2 — WCAG 2.2 Level AA

| Criterion | Conformance level | Remarks and explanations |
|---|---|---|
| 1.2.4 Captions (Live) | Not Applicable | No media. |
| 1.2.5 Audio Description (Prerecorded) | Not Applicable | No media. |
| 1.3.4 Orientation | Supports (code inspection) | No orientation locks. |
| 1.3.5 Identify Input Purpose | Supports (code inspection) | Access code uses `autocomplete="current-password"`; no other personal-data fields in owned surfaces. Clerk sign-in out of scope. |
| 1.4.3 Contrast (Minimum) | Not Evaluated | Token pairs pass: ink #232A33/white 14.5:1; muted #5C6670/white 5.9:1; teal #0E7C66/white 5.1:1 (test-enforced); white on #B0301C 6.4:1; white on #CF3A24 4.9:1. Brand #F0563F/white is 3.4:1 and appears decorative only in inspected rules — full state audit (hover, disabled, text over imagery) pending. |
| 1.4.4 Resize Text | Not Evaluated | 16px relative-friendly base; 200% zoom untested. |
| 1.4.5 Images of Text | Supports (code inspection) | Logo image only (exempt). |
| 1.4.10 Reflow | Not Evaluated | 320px layout constraints test-enforced for the workbench file input; narrow-layout media queries present; full 320 CSS px check pending. |
| 1.4.11 Non-text Contrast | Partially Supports (code inspection) | Focus indicator (3px #CF3A24) is 4.9:1 on white. **Form-field borders use #D9D4CF on white (1.5:1), below 3:1** in the workbench and hosted workspace. |
| 1.4.12 Text Spacing | Not Evaluated | — |
| 1.4.13 Content on Hover or Focus | Not Evaluated | No custom tooltips identified. |
| 2.4.5 Multiple Ways | Not Evaluated | — |
| 2.4.6 Headings and Labels | Not Evaluated | — |
| 2.4.7 Focus Visible | Supports (code inspection) | `:focus-visible` outline 3px on all surfaces (box-shadow ring on hosted workspace). |
| 2.4.11 Focus Not Obscured (Minimum) | Not Evaluated | — |
| 2.5.7 Dragging Movements | Supports (code inspection) | No drag interactions; reorder uses buttons. |
| 2.5.8 Target Size (Minimum) | Not Evaluated | Some workbench inputs are 32–34px tall; small inline buttons not measured. |
| 3.1.2 Language of Parts | Not Evaluated | — |
| 3.2.3 Consistent Navigation | Not Evaluated | — |
| 3.2.4 Consistent Identification | Not Evaluated | Shared four-step rail (Review/Understand/Improve/Verify) across workbench and hosted workspace (test-enforced). |
| 3.3.3 Error Suggestion | Not Evaluated | — |
| 3.3.4 Error Prevention (Legal, Financial, Data) | Not Evaluated | Destructive "Remove this synthetic record" sits inside a `<details>` disclosure; no confirmation step verified. |
| 3.3.8 Accessible Authentication (Minimum) | Supports (code inspection) — owned surfaces only | Staging access code is a password field permitting paste/password managers. Clerk/Entra sign-in and TOTP entry out of scope. |
| 4.1.3 Status Messages | Supports (code inspection) | Routine status `role="status"` polite; errors assertive; sponsor content never a live region (all test-enforced). |

## Known defects and remediation plan

| ID | Defect | Criterion | Target |
|---|---|---|---|
| ACR-1 | Form-field border contrast 1.5:1 | 1.4.11 | [DATE] |
| ACR-2 | No pause control for animations/sponsor content during processing | 2.2.2 | [DATE] |
| ACR-3 | No-JS meta refresh on progress page; 8-hour session expiry without warning | 2.2.1 | [DATE] |
| ACR-4 | Link-description inputs may lack a persistent visible label | 3.3.2 | [DATE] |
| ACR-5 | Complete AT testing (NVDA+Firefox, JAWS+Chrome, VoiceOver macOS/iOS, keyboard-only, 200%/400% zoom) | All "Not Evaluated" | Before pilot start |

## Legal disclaimer

This draft is based on internal code inspection and automated tests only and is provided for procurement discussion. It is not a third-party audit. [COUNSEL TO ADD STANDARD DISCLAIMER.]
