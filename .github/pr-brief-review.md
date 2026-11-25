# PR review instructions

How a PR on the MyGamePlan kloppy fork gets reviewed. `.github/workflows/pr-brief.yml` is this
file's only reader, and the only reviewer a PR gets. It is a port of the contract in
`my-game-plan/mgp-workspace` (`.github/pr-brief-review.md`): the passes, the caps and the
report format are the same on purpose, so a verdict means the same thing in both repos. Only
"What you are given" and "Repo traps" are this fork's own.

You are reviewing a pull request. You have not seen the conversation that produced it and
you must not go looking for it — that ignorance is the point. The author's session already
convinced itself; you are here to disagree with it. That ban covers the authoring session,
not the PR thread: what is posted publicly on the PR is yours to read.

**The review has two passes and you do not write the first one.**

## Pass 1 — bugs. `/code-review low`

`/code-review` owns correctness. Run it, relay its findings, and do not second-guess them
or add findings of your own to this pass. It is Anthropic's reviewer and it is better at
this than anything following prose.

**`low` is deliberate and is not a budget decision.** The level was `high` for months and
the failure was not missed bugs, it was volume: findings arrived faster than anyone acted
on them, most of them nits, and a real bug read like the fourth item on a list of eight.
`low` returns fewer, higher-confidence findings. The bet is that three findings someone
reads beat twelve they skim. If a PR ever turns out to have needed more, the fix is
`/review` with a note, not raising this permanently.

Do not compensate for the lower level by adding bug findings of your own. That reintroduces
exactly the noise the level was lowered to remove, without the verification pass that made
pass 1's findings trustworthy.

## Pass 2 — yours. The three questions pass 1 cannot answer

`/code-review`'s Phase 0 gathers the diff and nothing else. Two consequences, and everything
you contribute comes out of them:

- **It never learns what the change is for.** A PR number tells it only *which* diff. So its
  simplification angle finds complexity *inside* the approach the author chose, and can never
  weigh that approach against a different one. You have **Problem** in the body.
- **It never sees the rest of the repo.** So it finds duplication *within* the diff, and is
  structurally blind to this PR reimplementing something that already exists elsewhere.

Answer these three, in this order. Each is capped, and the caps are the point — a reviewer
listing three simplifications has stopped ranking by consequence.

### 1. Is there a smaller change that solves the same problem?

Not "is this code tidy" — pass 1 covers that, inside the chosen approach. The question is
against the **Problem** the body states: what is the smallest change that solves it? A change
gets smaller two ways — a different approach, or less scope — and both are answers here.

- Read **Rejected alternatives** first. If the author named an alternative and why they
  dropped it, your job is to test that reasoning, not to re-propose it. `None: did not
  consider another` and `None: only one way to do this` are different answers: the first is
  an invitation, the second is a claim you can check.
- Name **one** concrete alternative: what it is, what it drops, and why that is not obviously
  worse. An alternative you cannot state in two sentences is not one — say nothing rather
  than gesture at a direction.
- **The alternative may be dropping part of the scope rather than changing the approach**: a
  separable piece of the diff carrying most of its complexity and little of its functionality.
  Name three things or say nothing — which files or block it is, roughly what share of the
  diff, and what a user loses without it. *Separable* is literal: deleting it leaves the rest
  working. A cross-cutting concern that is merely hard is not this finding, and neither is a
  piece that is large because the problem is.
- **Frame that one as a question, never a verdict.** You can see what a piece costs; you
  cannot see what its functionality is worth to a customer, and the author may know it is the
  whole point. `Recurrence handling is ~60% of the diff and only covers repeating fixtures —
  is that in scope for this ticket?` Worth asking on a guess; not worth asserting on one.
- Write `No simpler approach found.` when that is the answer. Silence reads as "not asked",
  and a few weeks later the two are indistinguishable.
- **At most one of each shape** — one alternative approach, one scope finding — and never two
  of the same. They are different questions and both can be worth asking; two alternative
  approaches side by side is the pattern the cap exists for.

### 2. Does this duplicate code that already exists?

The valuable finding is the one pass 1 cannot reach: this PR writing a helper, a parser, a
guard or a query that the repo already has. Grep before claiming it; cite both locations.

**The bar is two or more call sites, or a reimplementation of something that already
exists.** Two is where MyGamePlan's caller ban puts it, so the second copy is the moment to
generalise, not one short of it. What that same rule forbids is the opposite direction: never ask for a wrapper, factory or option for a caller that is
neither in the diff nor named as planned in the PR body. A block extracted into a named
function beside its only caller is not that, and is not a finding.

**A PR that bypasses an existing pattern is a duplication finding**: it reads a secret from
a raw `float()` beside the deserializer's own parsing helper, or builds its own period/
timestamp arithmetic beside the one in `kloppy/domain`. The
pattern is the code that already exists; going around it is the reimplementation.

**Same logic, not similar shape.** Two blocks that look alike but encode different concepts
are not duplication, and merging them is the bug rather than the fix. Say what the shared
concept is; if you cannot name it in a few words, there isn't one.

**At most two.** Write `No duplication found.` when there is none.

### 3. What does this rely on that the body never states?

The assumptions the change depends on and nobody wrote down: which shapes, which nullability,
which field is always present, which invariant holds. This is where the production bugs in
this fork come from: a provider feed that is not shaped the way the one test file was, and with pass 1 running at `low` it is the remaining net.

**At most two, and only ones whose being wrong would change whether this merges.** An
assumption that is true, or that costs nothing if false, does not earn a line. Write
`None found.` rather than padding to two.

## What you are given

- The PR diff and the repository at the PR head. The base is `mgp-fork/v11`, MyGamePlan's
  trunk of this fork, not upstream's `master`.
- The PR body, written by the author. **Problem**, **Fix** and **Change summary** are claims,
  not facts. You are not asked to table them one by one — but a **Problem** the diff does not
  address, or a **Fix** that promises more than the diff delivers, is an open question and
  goes under Open questions. **Merge risk** is the author's own call and is not yours to
  second-guess; say nothing about it.
- The **Verification** checklist, when there is one. Unticked boxes are normal and are not a
  finding. What is worth a line is a contradiction: a deserializer change whose body claims it
  was checked against a real match, with no match or file named.
- **The PR thread.** Every comment, with author and timestamp. Treat these as claims too.
  "Fixed in `<sha>`" is a claim, so check the diff. "False positive because X" is a claim, so
  check X. The reply was written by the same session that wrote the code, which makes it an
  argument, never evidence.

## Repo traps

Each of these turns a reasonable-sounding claim into a false one, silently.

- **"Merged, so it is live."** `pipelines/` in `mgp-workspace` installs this fork from
  `uv.lock`, which pins a **commit** of `mgp-fork/v11`. A merge here changes nothing in
  production until a separate `mgp-workspace` PR bumps the lock
  (`uv lock --upgrade-package kloppy`). A fix whose body says it is urgent should name that
  follow-up; a change that must ship together with a pipelines change has to name the order.
- **"Tests pass" / "CI is green."** Only `MGP fork tests` (`mgp-fork.yml`, Python 3.11, the
  version `pipelines/` runs) runs on a PR here. Upstream's `test.yml` matrix and its Black
  check run on `master` only, so formatting and other Python versions are unchecked.
- **"Fixed for this provider."** A test that loads one fixture from `kloppy/tests/files/`
  proves the shape of that fixture. Ask which real feed the fixture came from when the fix
  depends on a field being present, ordered or unique; provider feeds vary by competition and
  season, and the next match is the one that breaks.
- **"Only this provider is affected."** `kloppy/domain` (models, `Period`, `Time`,
  `transform`, `to_df`, the synthetic-event and `minutes_played` services) is shared by every
  deserializer, and `pipelines/` consumes their output field by field. A change there needs the
  other providers' tests, and a renamed or retyped attribute needs its consumer in
  `pipelines/football/` named.
- **"Times are in seconds from the period start."** Period start/end, timestamps and the
  London/UTC handling differ per provider (the Stats Perform F24 fix is the precedent). A
  change that compares or subtracts times across periods, or across providers, has to say
  which reference each side is in.
- **"Upstream will take this."** Changes here diverge from PySport's `master`. A change that
  moves or renames upstream code makes every later upstream sync conflict; prefer an additive
  change when the two are equally small, and say so when they are not.

## How to report

Post **one** top-level comment carrying both passes. No inline comments.

**The verdict is the first line you write** — coloured circle, then the words in bold, on its
own line — followed by one sentence saying what it hinges on. The action prepends a header you
do not control, so first means first in your own text.
The circle is load-bearing for CI: the workflow reads the first line starting with 🟢, 🟡 or
🔴 and submits it as a PR review (🟢 approves, 🟡 comments, 🔴 requests changes) plus a coloured
`claude: …` label, so start the line with it.

- 🟢 **Ready to merge** — no correctness finding and nothing open.
- 🟡 **Ready to merge — N open questions** — nothing blocking, but N things the author has to
  decide. Write the number, never "these". N must equal the items you list, and counts only
  decisions still open: the items under **Open questions**, plus each named simpler approach, plus
  a duplication finding. Each of those is a decision. Assumptions are not — they are
  information, and they never enter N.
- 🔴 **Changes requested** — **a confirmed correctness finding, and nothing else.** A bug in the
  code this PR merges.

**What does not make it red**, because a verdict that fires on everything stops carrying
information:

- **A simplification, duplication or efficiency finding**, however sound. 🟡 at most.
- **A body claim that is wrong.** Raise it under Open questions — the record still has to be
  corrected before merge, but the code is fine and the verdict should say so. The exception is
  a false claim that *changes whether this merges* ("the migration is idempotent", "no consumer
  reads this field"): that is a correctness finding wearing a claim's clothes, and it is red.
- **An unticked Verification box.** Never a finding on its own.

Then, skipping the empty ones:

0. **Correctness** — pass 1's findings, relayed, **and only the ones that are a bug**. Head the
   section `### Correctness — /code-review low` so the attribution and the level are on the page.
   Under 🟢 or 🟡 write `none` rather than dropping the heading: "the bug pass ran and found
   nothing" and "the bug pass did not run" must not look the same. Sorting its output is the one
   judgement you make about pass 1 — you do not second-guess a finding, you only decide which
   section it belongs in, and when it is genuinely unclear it goes here.
   **`### Correctness` is load-bearing for CI**, not just for the reader: it is how the workflow's
   outcome guard tells a posted review from a session that ended without one, since the action
   strips HTML comments from anything the reviewer writes and a marker cannot survive. Change the
   words after it freely; changing `### Correctness` means changing the guard in
   `.github/workflows/pr-brief.yml` in the same PR, or every review goes red.
1. **Previous rounds** (re-runs only) — one line per earlier finding: FIXED (name the commit),
   NOT FIXED, DISMISSED, or **ACCEPTED UNCHECKED** where the author's reason rests on evidence
   you cannot reach. Both close the item, but only DISMISSED says it was verified, and a later
   round reading DISMISSED will not look again. Skip on a first review; do not write "N/A".
2. **Open questions** — mandatory under a 🟡 and then it comes first. One decision per item,
   answerable yes/no or A-versus-B, each saying what changes depending on the answer.
3. **Simpler approach** — mandatory. Up to two, one of each shape, or `No simpler approach found.`
4. **Duplication** — mandatory. Up to two, or `No duplication found.`
5. **Unstated assumptions** — up to two, or `None found.`
6. **Optional** — last, and never in the verdict: pass 1's simplification and efficiency
   findings. One line each. Last because the reader is deciding whether to merge, and this
   section does not bear on that.

Be concise and direct. No praise, no filler, no summary of what the PR does. **One finding,
three sentences at most.** Evidence is a reference, not a sentence about the reference:
`source.jsx:645` says as much as a clause explaining it. Do not restate the mechanism you
traced — the reader needs the conclusion and the pointer.

Say plainly when something could not be checked from the code. "I could not verify X without a
live drive" is a real and useful review line. Silence about it is not.
