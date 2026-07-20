# Coastline Accessibility Studio — Product Requirements Document

## From Document Remediation to an Accessibility Learning Journey

> Canonical PRD, July 2026. This version turns Accessibility Studio into a
> learning operating system — not merely a better checker. The central idea:
> every document defect becomes a teachable moment, every fix becomes
> evidence, and every repeated mistake becomes a product failure.
> Implementation status against this PRD is tracked in
> [`progress-ledger.md`](progress-ledger.md).

## 1. Executive summary

Coastline Accessibility Studio is a local-first document remediation and
learning platform that helps educators identify accessibility barriers,
understand their impact, repair what can be repaired, and develop the skills
to avoid creating those barriers again.

The product combines four capabilities in a single continuous loop:

**Review → Understand → Fix → Verify**

Most accessibility products stop at detection. Some attempt automated repair.
Almost none address the deeper problem: the people creating inaccessible
content are not learning from the process.

Accessibility Studio changes the unit of success. The goal is not merely to
produce a repaired PDF. The goal is to produce an instructor who creates more
accessible documents next time.

The experience should feel less like submitting a document to a compliance
scanner and more like progressing through a thoughtfully designed learning
journey. It borrows the strongest behavioral mechanics of products such as
Duolingo — short lessons, visible progress, practice loops, mastery levels,
streaks, challenges, and encouragement — without trivializing disability or
turning compliance into a game of collecting meaningless points.

Users earn progress by resolving real barriers and demonstrating
understanding, not by clicking through slides.

The platform remains honest about what software can and cannot determine. It
will never declare that a document is "fully accessible" or "compliant."
Instead, it distinguishes among:

- Machine-verifiable findings
- Human judgment decisions
- Items the system could not evaluate
- Repairs successfully applied and reverified
- Decisions attested to by the user

The result is a defensible evidence trail rather than a comforting but
unreliable green checkmark.

## 2. Product one-liner

Accessibility Studio turns inaccessible course materials into better
documents — and turns the people fixing them into better accessibility
practitioners.

## 3. Product thesis

Accessibility failures are not primarily a document problem. **They are a
feedback problem.**

An instructor creates a syllabus with poorly structured headings,
inaccessible tables, ambiguous link text, or images without meaningful
descriptions. The document is distributed. A student encounters the barrier.
The instructor may never learn that anything went wrong.

Traditional accessibility checkers identify defects but usually fail to
create understanding. Automated repair products may correct selected defects
but frequently conceal what changed, overstate what was accomplished, and
leave the author equally likely to produce the same problem again.

Accessibility Studio closes the feedback loop. Each review should help the
user answer five questions:

1. What is happening?
2. Who could be affected?
3. Why does it matter?
4. What can be safely fixed?
5. How do I prevent this next time?

The product succeeds when the user needs it less often.

## 4. The problem

Colleges manage thousands of instructional documents: syllabi, handouts,
scanned readings, assignment instructions, forms, presentations, tables and
data sheets, faculty-created PDFs, publisher materials, and legacy documents
with no editable source. Many contain barriers for students who use screen
readers, keyboard navigation, magnification, text-to-speech software,
alternative input devices, or other assistive technologies.

The current solutions are inadequate.

**Traditional checkers** produce technical findings without explaining their
instructional or human significance. They answer "which rule may have
failed?" They rarely answer "what would this experience be like for a
student?"

**Automated repair products** frequently create false confidence. They may
insert tags, generate descriptions, or restructure content without sufficient
certainty that the resulting document accurately reflects the author's
intent. They optimize for completion. Accessibility Studio optimizes for
truth.

**Training programs** are often disconnected from the documents instructors
actually create. Users complete a course, pass a quiz, and return to the same
workflows that created the problem. Training without application is quickly
forgotten. Accessibility Studio teaches inside the work.

## 5. Product vision

Accessibility Studio will become Coastline's accessibility learning operating
system: a platform where remediation, professional development, institutional
evidence, and continuous improvement reinforce one another.

- **For instructors:** a supportive environment for reviewing documents,
  fixing barriers, and building practical accessibility skills.
- **For accessibility specialists:** a consistent review framework, evidence
  trail, escalation pathway, and way to focus human expertise where judgment
  is genuinely required.
- **For instructional designers:** reusable learning pathways, templates,
  coaching interventions, and visibility into recurring content-design
  problems.
- **For institutional leadership:** evidence of participation, skill
  development, document improvement, recurring risks, and program impact —
  without collecting or uploading the instructional documents themselves.

## 6. Product principles

### 6.1 Honest by design

The system will never claim that software has proven a document fully
accessible or legally compliant.

Permitted outcome language: *machine-verified; resolved and rechecked;
requires human judgment; user-attested; not reviewed; unable to evaluate.*

Prohibited language: *fully compliant; guaranteed accessible; passed
accessibility; certified accessible.*

### 6.2 Learning is part of the workflow

Training will not live in a separate library that users are expected to visit
later. Every finding becomes a contextual micro-lesson. Every repair becomes
an opportunity to practice. Every repeated defect becomes a personalized
review recommendation.

### 6.3 Progress must represent real competence

Users do not earn mastery points for opening a lesson or pressing "Next."
Progress is awarded for evidence-producing actions: correctly identifying a
barrier, choosing the appropriate repair, applying a repair, rechecking the
result, correctly resolving a judgment scenario, demonstrating the skill in a
later document, and avoiding the same defect in future work.

### 6.4 Machines handle certainty; people handle meaning

Machines should perform deterministic, repeatable operations when they can do
so safely. Humans must remain responsible for decisions involving meaning,
context, instructional intent, and equivalence.

### 6.5 The original is never destroyed

All changes are applied to a copy. Every mutation must be explicitly
approved, logged, reversible where feasible, recorded with before-and-after
fingerprints, and rechecked after completion.

### 6.6 Privacy is architectural

Course documents remain on the user's computer. The default product requires
no document upload, no cloud document storage, no external AI processing, no
document-content telemetry, and no reuse of document content for training.
Optional institutional reporting may transmit only approved metadata, never
the document itself.

### 6.7 The product must itself be accessible

Accessibility Studio must model the practices it teaches: complete keyboard
navigation, screen-reader compatibility, visible focus states, reduced-motion
preferences, high zoom and reflow, plain-language instructions, non-color
status indicators, accessible charts and progress visualizations, and
captions and transcripts for all instructional media.

A product teaching accessibility while failing accessibility would be a
particularly expensive joke.

## 7. Core experience model

The product experience is organized around four verbs, which should appear
throughout the interface, onboarding, navigation, and reporting:

- **Learn** — understand the barrier and its impact.
- **Fix** — repair what can be safely repaired.
- **Prove** — recheck the result and create evidence.
- **Improve** — build mastery and reduce future defects.

## 8. Primary user personas

### 8.1 The time-pressed instructor

Limited accessibility knowledge; may feel anxious or defensive; wants clear
instructions without technical jargon; needs to know what matters most;
benefits from immediate, practical feedback.

Promise: *"We will help you fix the most consequential barriers without
making you become a PDF engineer."*

### 8.2 The accessibility specialist

Strong subject-matter knowledge; overloaded with manual requests; needs
consistent evidence; wants machines to handle repetitive checks; needs clear
escalation and judgment queues.

Promise: *"Spend your expertise on questions that require expertise."*

### 8.3 The instructional designer

Works across departments; wants reusable patterns; needs insight into
recurring faculty challenges; may lead workshops or improvement campaigns.

Promise: *"Turn real document problems into targeted learning
interventions."*

### 8.4 The institutional administrator

Does not need access to document contents; needs trend data and evidence;
wants to identify recurring risks; needs to demonstrate sustained
improvement.

Promise: *"See whether the institution is getting better, not merely
busier."*

## 9. The accessibility journey

The learning experience is structured as a progressive skill map with two
entry paths that eventually converge:

- **Document-first path:** the user reviews a real document; findings
  automatically create personalized lessons and recommended practice.
- **Learning-first path:** the user selects a guided journey and practices
  with safe examples before applying the skill to a real document.

Knowledge without application is incomplete. Repair without understanding is
fragile.

## 10. Skill map

Presented as a visual journey rather than a course catalog.

| World | Focus | Capstone |
|---|---|---|
| 1. Accessibility Foundations | What accessibility means; how students encounter barriers; automated checks vs human judgment; why "no errors detected" ≠ accessible; how assistive technologies interpret content | Experience a poorly structured document through simulated linear reading order and identify the barriers |
| 2. Structure That Communicates | Titles, primary language, heading hierarchy, reading order, lists, paragraph structure, page/section organization | Transform a visually formatted syllabus into one with meaningful semantic structure |
| 3. Images and Meaning | Informative/decorative/functional images, charts, alt text, long descriptions, context-dependent meaning | Review several images: describe, mark decorative, or rely on surrounding text |
| 4. Links, Navigation, and Interaction | Descriptive links, keyboard navigation, bookmarks, tables of contents, forms and labels, focus order, non-visual instructions | Repair a document with ambiguous links, unlabeled controls, and visual-only instructions |
| 5. Tables and Data | Header cells, relationships, simple vs complex tables, captions, reading order, when to redesign, accessible alternatives | Convert a visually arranged grid into a meaningful data table or better format |
| 6. Visual Access | Contrast, color-independent meaning, sizing, reflow, spacing, legibility, emphasis | Repair a document whose instructions and status rely entirely on color and styling |
| 7. PDF Survival and Escape Routes | When a PDF is repairable; when to edit the source; when OCR is necessary; limits of automated tagging; when to convert to accessible HTML | Choose the correct remediation strategy for several difficult documents |

## 11. Lesson design

Each learning unit takes approximately three to seven minutes and follows
the same behavioral sequence:

1. **Encounter** — show a realistic document situation.
2. **Experience** — demonstrate what the barrier does to a student or
   assistive technology.
3. **Explain** — short, plain-language explanation.
4. **Decide** — the user identifies the correct response.
5. **Repair** — the user completes the repair.
6. **Verify** — show the before-and-after result.
7. **Transfer** — apply the skill in a different context or real document.

This is not a video library with quizzes attached. It is guided practice.

## 12. Behavioral and motivational design

Game mechanics are allowed; gamifying disability or institutional liability
is not. The model is mastery motivation, not entertainment for its own sake.

### 12.1 Progress path

Users see current skill level, completed lessons, skills needing practice,
upcoming challenges, recently demonstrated competencies, and a suggested
next action.

### 12.2 Accessibility points

Points are earned for meaningful actions only: reviewing a document,
resolving a verified finding, completing a judgment decision, rechecking a
repaired document, completing a skill challenge, demonstrating transfer, and
going multiple documents without repeating a learned defect. Points never
imply legal compliance.

### 12.3 Streaks

Humane streaks only — weekly practice, documents improved this month,
consecutive reviews with no repeated heading defects, judgment queue kept
current — with grace periods and no punitive language. Accessibility
education should not become a guilt machine.

### 12.4 Mastery levels

Each skill progresses through evidence-based states:

1. **Introduced** — user has encountered the concept.
2. **Practiced** — user has completed a guided example.
3. **Applied** — user has used the skill in a real document.
4. **Verified** — the resulting repair was successfully rechecked.
5. **Sustained** — the defect has not recurred across subsequent eligible
   documents.

### 12.5 Challenges

Find the barrier; choose the correct fix; explain who is affected; repair
the example; compare two remediation options; decide whether automation is
safe; determine when HTML is the better format; review a document with
multiple interacting defects.

### 12.6 Milestones and badges

Badges reflect demonstrated practice, not attendance: Heading Architect,
Meaningful Image Reviewer, Table Translator, Keyboard Path Finder, PDF Escape
Artist, Evidence Builder, No False Passes. Institutional badges are called
practice credentials or skill milestones, never accessibility
certifications.

## 13. Personalized learning without AI

Personalization is deterministic. The recommendation engine uses finding
categories, repeat frequency, severity, mastery state, time since last
practice, unresolved judgment decisions, document types reviewed, and repair
outcomes.

Example: a user repeatedly produces skipped heading levels → the system
recommends a two-minute heading refresher, a guided heading repair, a
real-document challenge, and a later review to confirm the defect has
stopped recurring.

The companion voice is driven by authored content, rule-based state, and
approved message templates. It does not invent explanations, generate
alternative text, infer instructional intent, or make compliance decisions.

## 14. Core product surfaces

### 14.1 Home: Today's Accessibility Path

Continue current document; recommended next lesson; unresolved judgment
items; recent verified fixes; current mastery progress; weekly goal;
institutional campaign when applicable. The primary call to action is always
obvious: "Continue your next best step."

### 14.2 Local Review Workbench

The user selects a document and runs a local review. The workbench displays
review progress, categories examined, local-processing confirmation, tool and
ruleset versions, and counts of findings, judgment items, and unreviewable
items. Results are sorted into:

- **Technical Findings** — objective evidence of a defect or missing
  property.
- **Needs Your Judgment** — the system can identify the decision but cannot
  determine the correct human answer.
- **Could Not Review** — the system could not safely evaluate the item.
- **Verified Strengths** — selected checks that were successfully verified,
  shown as evidence but never combined into an overall accessibility pass.

### 14.3 Finding card

Plain-language title; what was detected; why it matters; who may be
affected; evidence from the document; confidence or verification status;
recommended action; whether an automatic fix is available; how to fix at the
source; related skill lesson; "show me the student experience" demonstration
where feasible.

### 14.4 Fix Lab

Review the proposed mutation; provide required information; preview the
change; approve or cancel; apply to a copy; recheck the modified copy;
compare before and after; undo or produce another copy.

Deterministic repairs include: adding a user-supplied document title;
setting a user-selected primary language; marking an image decorative after
explicit user judgment; applying user-provided alternative text; correcting
selected metadata; rebuilding certain structural elements when certainty is
sufficiently high.

### 14.5 Judgment Queue

Separates decisions requiring human meaning from technical errors. Each item
provides the decision to be made, relevant context, examples, a short
practice prompt when needed, an attestation field, escalation to a
specialist, and status history.

### 14.6 Recheck and Evidence View

After repair, the system reruns relevant checks and shows findings before
and after, resolved items, remaining items, new findings, human decisions
completed, items still requiring review, document fingerprint, tool and
ruleset version, timestamp, and the mutation log.

Example outcome: *6 findings before. 4 findings after. Resolved and
rechecked: Document title, Primary language. Remaining: 2 technical
findings, 2 judgment decisions.*

### 14.7 Editable HTML escape hatch

When PDF remediation is inefficient or structurally unreliable, users create
an editable HTML draft. The offline editor supports title, language,
semantic headings, lists, images and alternative text, decorative decisions,
links, tables, landmarks, a live unresolved-item checklist, and clean HTML
export. The system explains why HTML is being recommended.

### 14.8 My Learning Journey

Skill map; mastery state; recently demonstrated skills; recurring issues;
suggested practice; completed challenges; evidence-backed milestones;
personal improvement trends.

### 14.9 Accessibility Portfolio

A private record of demonstrated practice: skills applied, lessons
completed, repairs verified, judgment scenarios completed, document-type
experience, practice credentials, selected evidence receipts. The portfolio
must not expose document contents.

## 15. Institutional journey tooling

### 15.1 Campaigns

Focused initiatives (Accessible Syllabus Month, Heading Structure Week,
Meaningful Images Challenge, Accessible Tables Sprint, Spring Course
Readiness, New Faculty Accessibility Path) containing assigned lessons,
recommended reviews, due dates, office hours, department resources, and
milestones.

### 15.2 Cohorts

Users organized by department, school, faculty cohort, course type, training
program, employment classification, or support group. Cohort reporting
emphasizes support and improvement, not public ranking.

### 15.3 Institutional dashboard

Permitted aggregate metrics: participation rate, lessons completed,
documents locally reviewed, findings by category, verified repairs, judgment
items resolved, recurring-defect rate, time to resolution, HTML escape-hatch
use, skill mastery distribution, improvement by cohort, percentage of
documents with completed evidence receipts.

The dashboard must not display document contents, student information,
sensitive course materials, individual public leaderboards, or unqualified
compliance scores.

### 15.4 Risk and support view

Patterns (high recurrence of heading defects, many scanned documents,
unresolved judgment queues, departments relying on complex PDFs, heavy
table findings, repeatedly unevaluable documents) are converted into
recommended support actions, e.g. *"The Nursing cohort has a high
concentration of complex tables. Consider offering the Accessible Tables
workshop and providing approved table templates."*

## 16. Privacy and data architecture

**Local data** (on the user's device): document contents, previews, repair
copies, review results, findings, alternative text, human judgments,
fingerprints, mutation logs.

**Optional institutional metadata** (with configuration and notice):
pseudonymous user identifier, lesson completion, mastery state, finding and
repair category counts, review timestamp, tool and ruleset versions,
evidence-receipt identifier, department or cohort, user-selected document
type.

**Never synced:** full documents, extracted text, images, file contents,
alternative text, student data, document titles or filenames by default,
course identifiers unless explicitly enabled.

## 17. Evidence model

Every completed review produces an **evidence receipt** containing: file
fingerprint; date and time; Accessibility Studio version; ruleset version;
checks performed; checks not performed; technical findings; verified
repairs; human decisions; unresolved items; items the system could not
evaluate; output-file fingerprint; mutation history.

Required disclaimer: *"This receipt records the review actions completed
with Accessibility Studio. It is not a certification that the document is
fully accessible or legally compliant."*

## 18. North-star metric

**Repeat Defect Reduction** — the percentage reduction in previously taught
accessibility defects across subsequent eligible documents.

This measures whether the product is changing behavior. A system that
repairs 10,000 documents while users continue creating the same defects is a
maintenance utility. A system that reduces future defects is a
transformation platform.

## 19. Supporting metrics

**User outcomes:** time to first verified fix; percentage completing the
review-fix-recheck loop; judgment completion rate; lesson-to-application
conversion; skill mastery growth; repeat-defect rate; percentage choosing
source remediation over PDF repair; user confidence before/after a journey;
percentage of findings understood without specialist support.

**Institutional outcomes:** reduction in recurring defect categories;
specialist hours saved; documents with evidence receipts; reduction in
judgment backlog; increase in HTML/source-first remediation; participation
across departments; campaign completion; improvement in high-risk document
categories.

**Product quality:** false-positive rate; false-negative discoveries; repair
failure rate; recheck consistency; crash or corruption rate; percentage of
mutations successfully reversed; keyboard-only task completion;
screen-reader task completion; accessibility conformance of the application
itself.

## 20. Functional requirements

**Review engine:** run locally; deterministic rules; identified rule
versions; findings distinguished from judgment items; unsupported checks
reported; evidence preserved; no overall pass/fail claims.

**Repair engine:** operate on a copy; explicit permission; show the proposed
change; log every mutation; recheck relevant rules; preserve the original;
prevent unsupported silent repairs.

**Learning engine:** map findings to skills; recommend deterministic
learning activities; track evidence-based mastery; support spaced review;
detect repeated eligible defects; provide practice scenarios; connect
learning to real-document application.

**Journey engine:** skill maps; assignments and campaigns; cohorts; progress
tracking; privacy boundaries; aggregate reporting; no public shaming or
individual compliance scoring.

**Evidence engine:** review receipts; before-and-after fingerprints; tool
and ruleset versions; judgment decisions; unresolved limitations;
human-readable export; receipt integrity verification.

## 21. Non-goals

Accessibility Studio will not: guarantee legal compliance; replace qualified
accessibility professionals; automatically invent alternative text; decide
whether an image is meaningful; infer instructional intent; silently
restructure complex documents; upload documents for cloud processing; use
document contents to train models; reduce accessibility to a single score;
reward superficial lesson completion; punish users for breaking streaks;
publicly rank faculty by accessibility performance.

## 22. Product voice

Direct, respectful, calm, encouraging, honest, occasionally playful, never
patronizing, never falsely reassuring.

- During review: *"Looking for barriers a screen reader may encounter."*
  *"Some questions require human judgment. That is not a system failure; it
  is where meaning lives."*
- After a finding: *"This is fixable."* *"You know what this image means.
  The machine does not — and it should not pretend otherwise."*
- After repair: *"The title is now present and was confirmed during
  recheck."* *"One barrier removed. More importantly, you now know how to
  avoid it."*
- When recommending HTML: *"You could spend an afternoon wrestling this PDF.
  Or you could rebuild it correctly in a format designed for structure. We
  recommend the second option."*

## 23. Phased delivery

1. **Honest Local Review** — local selection, deterministic checks, finding
   categories, plain-language cards, no false compliance claims, exportable
   report.
2. **Fix and Verify** — permission-gated repairs to a copy,
   before-and-after fingerprints, recheck workflow, evidence receipts,
   Judgment Queue.
3. **Learning Journey** — skill map, contextual micro-lessons, guided
   challenges, mastery states, deterministic recommendations, repeat-defect
   tracking, Accessibility Portfolio.
4. **HTML Escape Hatch** — local conversion, built-in offline editor,
   semantic-structure tools, image decision workflow, live checklist, clean
   export.
5. **Institutional Transformation** — cohorts, campaigns, aggregate
   dashboards, skill-gap reporting, program effectiveness, support
   recommendations, privacy-preserving metadata sync.

## 24. Demo narrative

**Opening:** "Most accessibility products inspect a document. Accessibility
Studio improves the document and the person who created it."

**Honest review:** run the local review on a syllabus. "The file never
leaves this computer. The tool separates what it can prove, what requires
human judgment, and what it could not evaluate. It never calls the document
compliant — that word requires more evidence than a checker can honestly
provide."

**Teaching moment:** open the Primary Language finding. "The learning
happens at the exact moment it becomes relevant."

**Fix and prove:** apply title and language to a copy. "Two items were
resolved and verified. Four remain. That is more useful than a green
checkmark because it is true."

**Learning journey:** open the skill map. "Progress is earned when a skill
is demonstrated in a real document — not when someone watches a video.
Introduced → Practiced → Applied → Verified → Sustained. The final level is
not 'I passed the quiz.' It is 'I stopped creating the defect.'"

**Escape hatch:** create the editable HTML draft, make the improvements,
export clean HTML.

**Institutional view:** show the aggregate dashboard. "The real question is
not how many documents we scanned. It is whether we are producing fewer
barriers."

## 25. Positioning

Most tools compete on the number of errors detected or repairs claimed.
Accessibility Studio competes on trust, learning, and sustained behavior
change. Its moat is not merely technical. **Its moat is the refusal to
pretend.** It does not claim certainty where certainty does not exist, hide
judgment behind automation, confuse activity with competence, or declare
victory because a progress bar reached 100%.

On AI, the product no longer leads with "no AI." The stronger claim:
**Accessibility Studio works without AI. When AI is enabled, the customer
chooses the model, controls the key, controls what leaves the device, and AI
never decides compliance.** See
[`ai-architecture-byok.md`](ai-architecture-byok.md).

## 26. Closing product statement

Every other tool asks: *"Did this document pass?"*

Accessibility Studio asks: *"What barriers could a real student encounter,
what evidence do we have, what can we responsibly fix, and what will the
author do differently next time?"*

That is a harder question. It is also the one that changes outcomes.

The sharpest strategic addition is the **Sustained** mastery level: a user
does not master headings because they passed a lesson; they master headings
when the problem stops appearing in their work. That gives Coastline a
north-star metric few competitors can credibly claim.
