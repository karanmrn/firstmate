# Crew knowledge

Crew knowledge is how lanes in a firstmate home share what they learn without routing every fact through firstmate.
It has three parts: a knowledge board (durable shared entries with provenance and expiry), lane-to-lane peer messages (point-to-point records in the steering inbox, with a copy firstmate can see), and overlap detection (which live lanes are touching the same files).
Decisions stay with firstmate: nothing on the board and no peer message is an instruction, an approval, or a decision close.

## Ownership

- `bin/fm-knowledge.sh` owns the board: the record format, the fold, the render, the expiry rules, and the overlap computation.
- `bin/fm-task-inbox-lib.sh` owns the peer record shape inside the steering inbox, exactly as it owns the firstmate steer record shape.
- `bin/fm-send.sh` owns the peer send path (`--from`) and the per-lane peer traffic logs.
- `bin/fm-brief.sh` owns the Knowledge section of ship and scout briefs, the worker-facing half of the contract.
- `bin/fm-session-start.sh` owns the digest placement; `bin/fm-knowledge.sh digest` owns the digest content.
- This document is the contract those headers point at. Change behaviour here first, then patch the owner.

## Board storage

Everything lives under `state/knowledge/` in the home's state dir, gitignored like all state.

- `entries.jsonl` is the only authoritative store: an append-only log, one JSON object per line.
- `BOARD.md` is a rendered view, regenerated atomically (temp file plus rename) on every mutation. Never edit it by hand.
- `.lock` is an flock that serializes every mutation and render, so a lane and firstmate writing at the same moment cannot interleave a line or ship a stale board.

### Record ops

The log is event-sourced. Each line carries an `op`:

- `add` - a full entry record (fields below).
- `confirm` - `{op, id, at, expires_at}`: renews the entry for its own `ttl_days` and stamps `confirmed_at`.
- `expire` - `{op, id, at}`: tombstones an entry whose lifetime has run out. Written by the `expire` sweep.
- `delete` - `{op, id, at, by}`: tombstones immediately. Firstmate-only (see Safety rules).

A reader folds the log top to bottom.
A trailing partial line from a crashed writer is skipped with a stderr warning, never mistaken for an entry.

### Entry fields

| field | meaning |
| --- | --- |
| `op` | `add`, `confirm`, `expire`, or `delete` |
| `id` | `k-<yyyymmdd>-<6 hex>`, unique per add |
| `project` | project name the entry belongs to, or `fleet` for cross-project knowledge |
| `kind` | `fact`, `recipe`, `hazard`, or `overlap` |
| `title` | one-line summary |
| `body` | the knowledge itself; newlines allowed |
| `tags` | list of short lowercase tags for search |
| `source` | the lane id that wrote the entry, or `firstmate` |
| `evidence` | the commit, path, or path:line that backs the entry, when one exists |
| `created_at` | UTC timestamp of the add |
| `confirmed_at` | UTC timestamp of the latest confirm |
| `ttl_days` | the renewal span applied by every later confirm |
| `expires_at` | UTC timestamp after which the entry is stale |

### Lifetimes

- `fact`: 14 days
- `hazard`: 14 days
- `recipe`: 60 days
- `overlap`: 3 days (lane overlap goes stale faster than any fact)

`confirm` re-arms an entry for its own `ttl_days` counted from the moment of confirmation.
`expire` appends a tombstone for every entry whose `expires_at` has passed.
Reads filter out expired and tombstoned entries unless `--include-expired` is given.

## Commands

```
bin/fm-knowledge.sh add --project <p> --kind <fact|recipe|hazard|overlap> \
    --title <t> --body <b> [--tags a,b] [--source <lane>] [--evidence <ref>] [--ttl-days N]
bin/fm-knowledge.sh list [--project <p>] [--kind <k>] [--include-expired]
bin/fm-knowledge.sh search <query> [--project <p>]
bin/fm-knowledge.sh confirm <id>
bin/fm-knowledge.sh delete <id> --as firstmate
bin/fm-knowledge.sh expire
bin/fm-knowledge.sh render [--project <p>]
bin/fm-knowledge.sh overlaps
bin/fm-knowledge.sh digest
```

- `add` prints the new entry id.
- `list` and `search` print one line per matching entry: id, kind, project, expiry date, title.
- `render` rewrites `BOARD.md` with every live entry grouped by project and kind, prints the board to stdout (filtered to `--project` when given), and ends with an "Active lanes touching this area" block built from the overlap computation, so a worker sees who else is active before editing.
- `overlaps` prints the raw lane pairs and the files and top-level directories they share, with no board mutation.
- `digest` prints the bounded session-start summary and nothing else.

## Lane-to-lane peer messages

A lane sends a fact or a question to another lane directly:

```
bin/fm-send.sh --from <own-task> <target-task> "the auth module already handles token refresh; see src/auth/refresh.c"
```

The message lands in the target's steering inbox as a peer record:

```
schema=fm-task-inbox.v1
at=<utc>
kind=peer
from=<own-task>
--
<exact message text>
```

The record rides the same durable inbox, the same sequence allocation, and the same acknowledgement contract as a firstmate steer: the receiver reads it in numeric order and moves it to `handled/`.
The doorbell names the record as peer traffic, so a receiver whose brief predates this contract still learns from the line itself that the message is information from another lane.
The watcher re-ring ladder treats an unacknowledged peer record exactly like an unacknowledged steer.

A peer record is never a decision, never an instruction, and never a lifecycle control.
`fm-send` refuses `--from` combined with `--resolve-key`, `--key`, or `--fire-and-forget`; refuses a message whose text begins with `/` or `$` (harness-native invocations belong to firstmate's typed plane); refuses a secondmate, remote, explicit-backend, or self target; and refuses a sender id with no metadata in this home.
Firstmate-authored records keep their current precedence: they arrive as ordinary instruction records, and only they can carry `--resolve-key` decision closes.

Every peer send appends one identical line to `state/<from>.peer.log` and `state/<target>.peer.log`:

```
<utc> <from> -> <target> [seq NNN] <excerpt, capped at 120 chars>
```

The session digest tails those logs so firstmate sees the traffic without reading either lane's pane.

## Overlap detection

`overlaps` reads every `state/<id>.meta`, keeps records whose `worktree=` is an existing git worktree, and skips `kind=secondmate` records, whose worktree is a whole home rather than a lane.
For each remaining lane it diffs the worktree against its default-branch base (`origin/HEAD`, else `origin/main`, `origin/master`, then local `main` or `master`) with `git diff --name-only <base>`, so committed and uncommitted lane changes both count.
Two lanes overlap when their changed-file sets share at least one exact path or one top-level directory, and only when both lanes work on the same project; identical directory names in different repos are not an overlap.
Each lane's git probe runs under a short timeout, and a lane that cannot be read is reported as unreadable rather than failing the whole run.
The lane set is bounded by `FM_KNOWLEDGE_OVERLAP_MAX_LANES` (default 12) so the session digest stays cheap; any remainder is counted and disclosed.

## Safety rules

- No secrets: `add` rejects any field matching private-key blocks, common token shapes (AWS, GitHub, OpenAI, Slack, Google, JWT), `password`/`token`/`api_key`-style assignments, and long high-entropy runs. The refusal names the pattern class, never the matched text.
- Facts, not authority: a board entry or peer message never changes a task's brief, closes a decision, or authorizes anything. Firstmate's records keep precedence in the inbox.
- Provenance is mandatory: every entry names its source lane and, when it exists, the commit or path that backs it, so a later lane can verify before trusting.
- Append-only store: mutations are log lines plus an atomic re-render; a crash can waste a partial trailing line but cannot corrupt earlier entries.
- Fail closed: a missing `FM_HOME`, a missing state dir, a malformed record, an unknown kind, or an unreadable worktree is a loud error or an explicit `unreadable` note, never a silent skip.
- Bounded output: `digest` stays under 20 lines and `overlaps` bounds its lane set, so the session-start path stays cheap.
