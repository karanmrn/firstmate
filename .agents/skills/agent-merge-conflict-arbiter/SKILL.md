---
name: agent-merge-conflict-arbiter
description: >-
  Neutral arbiter for a git merge or rebase conflict between two agents' branches.
  Load when a merge or rebase halts on conflicts between two workers' tasks and neither original worker should adjudicate, before dispatching a worker to reconcile them, and when a brief names this skill.
  Not for conflicts inside one worker's own work, or for lockfiles and generated files that should be regenerated.
user-invocable: false
metadata:
  internal: true
  author: Nous Research (Hermes Agent)
  license: MIT
---

<!-- Adapted from Hermes Agent optional-skills/autonomous-ai-agents/agent-merge-conflict-arbiter at commit 2bd378ed1b8, Copyright (c) 2025 Nous Research, MIT License (see LICENSE in this directory). Hermes kanban and tool steps are replaced with git, gh, and Firstmate brief and status terms. -->

# Agent merge-conflict arbiter

Resolve a git merge conflict between two agents' branches as an impartial third party.
Agents resolving conflicts against a peer's work reliably either overwrite the peer or abandon their own change, because they lack the peer's context and are biased toward their own side.
This skill is the fix: a neutral reconciler that receives both diffs plus both sides' stated intents and produces a merged result, like a merge-queue arbiter.

This skill grants no new authority.
Firstmate never writes to a project, so arbitration is always worker work.
The reconciled branch still ships through its task's delivery mode, and merge authority, force, discard, and unlanded-work rules are unchanged.

## When to use

- Two workers' branches collide during parallel work, such as two ships whose changes touch the same files.
- `git merge` or `git rebase` halts on conflicts between two workers' tasks and neither original worker should self-adjudicate.
- Do not use it for conflicts within a single worker's own work, or for trivial lockfile or generated-file conflicts; regenerate those instead.

## Prerequisites

- An isolated task worktree containing the halted merge, or the two branch names plus a brief that authorizes running the merge there.
- Both sides' intent sources: each task's brief `## Captain's intent`, each PR body (`gh-axi pr view <number>`), or at minimum each branch's commit messages.
- The project's build and test commands, if they exist.

## How to run

**Standalone** - a worker loads this skill inside the conflicted worktree and follows the procedure top to bottom.

**Spawned neutral worker** - the preferred shape when two workers collide:

- Firstmate dispatches a third worker, never either conflicting worker, through the normal brief and spawn path.
- Its brief names the project, both branch names, and both sides' intent summaries verbatim, and tells the worker to load this skill.
- Both original tasks stay recorded, so their briefs, status records, and PRs remain readable as intent sources.

## Quick reference

| Hunk class | Definition | Resolution |
|---|---|---|
| disjoint-intent | The two changes serve different goals and can coexist | Combine both |
| same-question-different-answer | Both sides answered one design question differently | Pick ONE per stated intents; surface the decision |
| superseded | One side's premise no longer holds after the other's change | Keep the surviving side; note why |

Impartiality contract: never favor the side that spawned you.
Touch ONLY conflicted regions, with no drive-by edits.
Every design-question pick must appear explicitly in the hand-back summary.

## Procedure

### 1. Gather both sides

- Run `git status` to confirm the conflicted state, and `git diff --name-only --diff-filter=U` to list the conflicted files.
- Run `git merge-base <A> <B>`, then for each side `git log --oneline <base>..<side>` and `git diff <base>..<side> -- <file>` for every conflicted file.
  In a halted merge, `HEAD` is one side and `MERGE_HEAD` is the other.
  In a halted rebase, `HEAD` is the branch being rebased onto and `REBASE_HEAD` is the commit being replayed.
- Collect each side's intent from the task brief's `## Captain's intent`, the PR body (`gh-axi pr view <number>`), or the commit messages from the log above.
  Write down one sentence of intent per side before touching any file.
- Done when: you can state both intents in your own words and have both diffs for every conflicted file.

### 2. Check conflict types and classify hunks

- Inspect `git status --short` and `git ls-files -u` for every conflicted path before editing or staging.
- If any conflict requires a decision outside text markers, escalate before editing or staging any file.
  This includes modify/delete, rename/delete, rename/rename, binary, and other markerless conflicts.
  Record a `needs-decision:` status line with all affected paths, the conflict type, both intents, and the required decision.
  Leave the files and index unchanged.
  Deliver the escalation through step 5, then stop.
- Otherwise, open each conflicted file and locate each `<<<<<<<`/`=======`/`>>>>>>>` block.
- Assign each hunk exactly one class from the quick-reference table, judging by the stated intents, not by which change looks nicer.
- If a single hunk contains multiple independent decisions, such as new logic that combines cleanly plus a styling or rounding choice both sides answered differently, decompose it into sub-decisions and classify each one.
- A single file often mixes classes: one hunk may be a design collision while a neighboring hunk is disjoint.
  Classify per hunk, not per file.
- Continue only when every unmerged entry consists entirely of text hunks.
  Each hunk must have a written class and a one-line rationale.

### 3. Resolve under the impartiality contract

- Edit each hunk in place:
  - disjoint-intent -> merge both changes so each intent is fully served.
  - same-question-different-answer -> pick the answer that best serves the STATED intents.
    For example, an intent of "strict validation" beats "quick default" if the task required correctness.
    Never split the difference into a hybrid neither side asked for.
  - superseded -> keep the surviving side and delete the dead premise.
- Never favor the side that spawned you.
  If intents genuinely tie, append a `needs-decision:` status line naming the hunk, the design question, and both answers.
  Deliver the escalation through step 5, then stop.
- Change nothing outside conflict markers: no formatting, renames, or opportunistic fixes.
- Stage each resolved file with `git add` only after step 2 permits hunk resolution and all its hunks are resolved.
- Done when: every original unmerged entry is resolved, `git grep -n -e '^<<<<<<<' -e '^>>>>>>>'` finds no markers, `git diff --name-only --diff-filter=U` is empty, and every resolved file is staged.

### 4. Verify

- Run the project's build and tests; at minimum import or execute the touched modules.
  Both intents must be observable in the merged behavior, for example side A's new semantics and side B's disjoint addition both present.
- Complete the merge with `git commit`, or the rebase with `git rebase --continue`.
  The default merge message plus a body listing hunk decisions is fine.
- Done when: verification passes and the merge commit exists or the rebase has completed.

### 5. Hand back

- For completed arbitration, produce a summary naming EVERY hunk decision: `file:lines - class - which side(s) kept - rationale`.
- For every same-question-different-answer hunk, state the design question and the answer you picked so a human can veto it; never bury a design call.
- For an escalation, report every unresolved hunk or file-level conflict, all affected paths, both intents, and the required decision.
  State that the merge or rebase remains halted.
- Deliver the summary where the brief's definition of done puts it: a scout writes it to its report, and a ship carries it in its delivery evidence and final report.
  Standalone, print the summary.
- Done when: the report is delivered and accounts for every resolved hunk and unresolved conflict.

## Pitfalls

- **Self-favoring**: if you were spawned by one of the conflicting workers, you are structurally biased.
  State this and weigh the other side's intent deliberately.
  Prefer the third-worker shape so this never arises.
- **Splitting the difference** on a design collision produces a hybrid nobody designed; pick one answer and surface it.
- **Per-file classification**: files usually mix hunk classes; classifying a whole file as one class silently drops a disjoint change.
- **Drive-by edits** make the merge unreviewable and steal decisions from the original workers.
- **Missing intents**: commit messages alone can be thin; prefer task briefs or PR bodies.
  If neither side's intent is recoverable, escalate instead of guessing.
- **Repeat offenders**: repeated conflicts on the SAME file across rounds are a hotspot signal, not routine reconciliation work.
  Flag it with a `hotspot: <path> - <reason>` line in the hand-back summary so firstmate can decompose that file, rather than serially reconciling every new collision on it.

## Verification

For completed arbitration:

- `git status` shows a clean tree on the target branch with a merge commit or a completed rebase.
- No conflict markers remain (`git grep -n -e '^<<<<<<<' -e '^>>>>>>>'` prints nothing).
- Build and tests pass; both sides' intents are demonstrably present, or the dropped one is explicitly named in the summary.
- The hand-back summary enumerates every hunk with class and rationale.

For an escalation, the report accounts for every unresolved conflict and explicitly states that arbitration is incomplete.
For a step 2 escalation, the files and index remain unchanged.
