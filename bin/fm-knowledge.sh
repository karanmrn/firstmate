#!/usr/bin/env bash
# fm-knowledge.sh - the fleet knowledge board: shared facts, recipes, hazards,
# and overlap notes with provenance and expiry, plus live lane-overlap
# detection and the bounded session-start digest. Contract: docs/crew-knowledge.md.
#
# Usage:
#   fm-knowledge.sh add --project <p> --kind <fact|recipe|hazard|overlap>
#                       --title <t> --body <b>
#                       [--tags a,b] [--source <lane>] [--evidence <ref>] [--ttl-days N]
#   fm-knowledge.sh list [--project <p>] [--kind <k>] [--include-expired]
#   fm-knowledge.sh search <query> [--project <p>]
#   fm-knowledge.sh confirm <id>
#   fm-knowledge.sh delete <id> --as firstmate
#   fm-knowledge.sh expire
#   fm-knowledge.sh render [--project <p>]
#   fm-knowledge.sh overlaps
#   fm-knowledge.sh digest
#
# The full contract (data model, peer messages, overlap rules, safety rules) is
# owned by docs/crew-knowledge.md; this script implements it. Key mechanics:
#
# - Store: <state>/knowledge/entries.jsonl, an append-only event log (ops add,
#   confirm, expire, delete) folded on every read; BOARD.md is a rendered view
#   rewritten atomically on every mutation; .lock (flock) serializes writers.
# - TTL defaults: fact/hazard 14 days, recipe 60, overlap 3. confirm re-arms an
#   entry for its own ttl_days from the moment of confirmation.
# - Secret-shaped values (private keys, common token formats, credential
#   assignments, long high-entropy runs) are rejected on add; the refusal names
#   the pattern class, never the matched text.
# - Workers and firstmate both add and confirm; delete requires --as firstmate.
# - overlaps diffs each live task worktree (state/<id>.meta worktree=, skipping
#   kind=secondmate) against its default-branch base with `git diff --name-only
#   <base>` (committed and uncommitted changes both count) and reports lane
#   pairs in the same project sharing an exact path or a top-level directory.
#   The lane set is bounded by FM_KNOWLEDGE_OVERLAP_MAX_LANES (default 12).
# - digest prints the bounded (<20 line) session-start summary: live counts per
#   project, entries expiring within 24h, overlap pairs, recent peer traffic.
#
# Resolution follows fm-brief.sh: FM_HOME falls back to FM_ROOT_OVERRIDE and
# then the repo root; FM_STATE_OVERRIDE redirects the state dir for tests.
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FM_ROOT="${FM_ROOT_OVERRIDE:-$(cd "$SCRIPT_DIR/.." && pwd)}"
FM_HOME="${FM_HOME:-$FM_ROOT}"
STATE="${FM_STATE_OVERRIDE:-$FM_HOME/state}"

usage() {
  awk '
    NR == 1 { next }
    /^#/ { sub(/^# ?/, ""); print; next }
    { exit }
  ' "$0"
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
esac

if [ ! -d "$STATE" ]; then
  echo "error: state dir '$STATE' is missing; set FM_HOME to a firstmate home" >&2
  exit 1
fi
command -v python3 >/dev/null 2>&1 || {
  echo "error: python3 not found; fm-knowledge.sh requires python3" >&2
  exit 1
}

export FM_KNOWLEDGE_STATE="$STATE"
exec python3 - "$@" <<'FM_KNOWLEDGE_PY'
import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import fcntl
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATE = Path(os.environ["FM_KNOWLEDGE_STATE"])
KDIR = STATE / "knowledge"
LOG = KDIR / "entries.jsonl"
BOARD = KDIR / "BOARD.md"
LOCK = KDIR / ".lock"

KINDS = ("fact", "recipe", "hazard", "overlap")
KIND_ORDER = {"hazard": 0, "fact": 1, "recipe": 2, "overlap": 3}
KIND_HEADINGS = {"hazard": "Hazards", "fact": "Facts", "recipe": "Recipes", "overlap": "Overlap notes"}
DEFAULT_TTL = {"fact": 14, "hazard": 14, "recipe": 60, "overlap": 3}
DIGEST_LINE_CAP = 16

SECRET_PATTERNS = [
    ("private key block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("OpenAI-style API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("credential assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|api[_-]?secret|secret[_-]?key|access[_-]?token|auth[_-]?token|"
        r"client[_-]?secret|password|passwd)\b\s*[:=]\s*[\"']?[^\s\"']{8,}")),
    ("long high-entropy token", re.compile(
        r"\b(?=[A-Za-z0-9_\-]*[a-z])(?=[A-Za-z0-9_\-]*[A-Z])(?=[A-Za-z0-9_\-]*[0-9])[A-Za-z0-9_\-]{40,}\b")),
]


def die(msg):
    print("error: " + msg, file=sys.stderr)
    sys.exit(1)


def utcnow():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def scan_secrets(field, value):
    if not value:
        return
    for name, rx in SECRET_PATTERNS:
        if rx.search(value):
            die("--{} matches a {} pattern; knowledge entries never carry secrets. "
                "Store a pointer (path, commit, key name), not the secret itself.".format(field, name))


@contextmanager
def locked():
    KDIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def append_op(rec):
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def fold():
    entries = {}
    tombstoned = set()
    if not LOG.exists():
        return entries, tombstoned
    with LOG.open("r", encoding="utf-8", errors="replace") as fh:
        for n, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                print("warning: {}:{}: unparseable log line skipped (crashed writer?)".format(LOG, n),
                      file=sys.stderr)
                continue
            if not isinstance(rec, dict):
                print("warning: {}:{}: non-object log line skipped".format(LOG, n), file=sys.stderr)
                continue
            op = rec.get("op")
            eid = rec.get("id")
            if op == "add" and isinstance(eid, str) and eid:
                entries[eid] = rec
                tombstoned.discard(eid)
            elif op == "confirm" and eid in entries and eid not in tombstoned:
                if rec.get("at"):
                    entries[eid]["confirmed_at"] = rec["at"]
                if rec.get("expires_at"):
                    entries[eid]["expires_at"] = rec["expires_at"]
            elif op in ("expire", "delete") and eid:
                tombstoned.add(eid)
    return entries, tombstoned


def entry_state(e, now, tombstoned):
    if e["id"] in tombstoned:
        return "deleted"
    exp = parse_ts(e.get("expires_at"))
    if exp is None or exp <= now:
        return "expired"
    return "live"


def is_live(e, now, tombstoned):
    return entry_state(e, now, tombstoned) == "live"


def is_stale(e, now, tombstoned):
    return entry_state(e, now, tombstoned) == "expired"


# --- lane overlap probing ---------------------------------------------------

def meta_fields(path):
    fields = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                fields[k.strip()] = v.strip()
    except OSError:
        pass
    return fields


def lane_base(worktree):
    for ref in ("origin/HEAD", "origin/main", "origin/master", "main", "master"):
        try:
            r = subprocess.run(
                ["git", "-C", worktree, "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
                capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if r.returncode == 0 and r.stdout.strip():
            return ref
    return None


def lane_changed_files(worktree):
    base = lane_base(worktree)
    if base is None:
        return None, None, "no default-branch base ref"
    try:
        r = subprocess.run(["git", "-C", worktree, "diff", "--name-only", base, "--"],
                           capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return None, base, "git diff timed out"
    except OSError as exc:
        return None, base, "git failed: {}".format(exc)
    if r.returncode != 0:
        return None, base, "git diff against {} failed".format(base)
    files = sorted({ln.strip() for ln in r.stdout.splitlines() if ln.strip()})
    return files, base, None


def max_lanes():
    raw = os.environ.get("FM_KNOWLEDGE_OVERLAP_MAX_LANES", "12")
    try:
        n = int(raw)
    except ValueError:
        return 12
    return n if n > 0 else 12


def probe_lanes():
    lanes = []
    for meta in sorted(STATE.glob("*.meta")):
        fields = meta_fields(meta)
        if fields.get("kind") == "secondmate":
            continue
        wt = fields.get("worktree", "")
        if not wt or not os.path.isdir(wt) or not os.path.exists(os.path.join(wt, ".git")):
            continue
        lanes.append({"id": meta.name[:-len(".meta")], "project": fields.get("project", ""), "worktree": wt})
    skipped = 0
    cap = max_lanes()
    if len(lanes) > cap:
        skipped = len(lanes) - cap
        lanes = lanes[:max_lanes()]
    for lane in lanes:
        files, base, err = lane_changed_files(lane["worktree"])
        lane["files"] = files or []
        lane["base"] = base
        lane["err"] = err
        lane["dirs"] = sorted({p.split("/")[0] + ("/" if "/" in p else "") for p in lane["files"]})
    pairs = []
    readable = [l for l in lanes if l["err"] is None]
    for i in range(len(readable)):
        for j in range(i + 1, len(readable)):
            a, b = readable[i], readable[j]
            if a["project"] and b["project"] and a["project"] != b["project"]:
                continue
            shared_files = sorted(set(a["files"]) & set(b["files"]))
            shared_dirs = sorted(set(a["dirs"]) & set(b["dirs"]))
            if shared_files or shared_dirs:
                pairs.append({"a": a["id"], "b": b["id"], "files": shared_files, "dirs": shared_dirs})
    return lanes, pairs, skipped


def proj_label(project):
    p = project.rstrip("/")
    base = os.path.basename(p)
    return base or p or "?"


def project_matches(entry_project, want):
    if not want:
        return True
    ep = (entry_project or "").rstrip("/")
    wp = want.rstrip("/")
    return ep == wp or os.path.basename(ep) == wp or ep == os.path.basename(wp)


def recent_peer_lines(n):
    # One line per peer message is mirrored to both the sender's and the
    # target's <id>.peer.log (bin/fm-send.sh owns the write), so collect the
    # tail of each log and de-duplicate identical lines before taking the
    # newest n. Lines begin with an ISO-8601 UTC timestamp, so a lexical sort
    # of the deduplicated set is also chronological.
    seen = set()
    for log in sorted(STATE.glob("*.peer.log")):
        try:
            tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
        except OSError:
            continue
        for ln in tail:
            ln = ln.rstrip()
            if ln:
                seen.add(ln)
    return sorted(seen)[-n:]


def build_board(entries, tomb, now, lanes, pairs, skipped, project_filter=None):
    live = [e for e in entries.values() if is_live(e, now, tomb)]
    if project_filter:
        live = [e for e in live if project_matches(e.get("project", ""), project_filter)]
    stale = sum(1 for e in entries.values() if e["id"] not in tomb and is_stale(e, now, tomb))
    deleted = len(tomb)
    lines = ["# Fleet knowledge board", ""]
    lines.append("Rendered {} by bin/fm-knowledge.sh from entries.jsonl{}: {} live, {} past expiry, "
                 "{} retired (only live entries shown).".format(
                     iso(now), " filtered to project '{}'".format(project_filter) if project_filter else "",
                     len(live), stale, len(tomb)))
    lines.append("Entries expire 14 days after their last confirm (facts, hazards), 60 (recipes), "
                 "or 3 (overlap notes); renew with `bin/fm-knowledge.sh confirm <id>`.")
    lines.append("")
    if not live:
        lines.append("(no live entries)")
        lines.append("")
    by_proj = {}
    for e in live:
        by_proj.setdefault(e.get("project") or "fleet", []).append(e)
    for proj in sorted(by_proj):
        group = sorted(by_proj[proj], key=lambda e: (KIND_ORDER.get(e.get("kind"), 99),
                                                     e.get("created_at", ""), e.get("id", "")))
        lines.append("## Project: {}".format(proj))
        lines.append("")
        for kind in KIND_ORDER:
            group_k = [e for e in group if e.get("kind") == kind]
            if not group_k:
                continue
            lines.append("### {}".format(KIND_HEADINGS[kind]))
            lines.append("")
            for e in group_k:
                lines.append("- **{}** {}".format(e["id"], e.get("title", "")))
                body = e.get("body", "")
                for bl in (body.splitlines() or [""]):
                    lines.append("  " + bl if bl else "")
                bits = []
                if e.get("tags"):
                    bits.append("tags: " + ", ".join(e["tags"]))
                bits.append("source: " + str(e.get("source") or "?"))
                if e.get("evidence"):
                    bits.append("evidence: " + str(e["evidence"]))
                bits.append("added " + str(e.get("created_at", "?")))
                bits.append("expires " + str(e.get("expires_at", "?"))[:10])
                lines.append("  " + " | ".join(bits))
            lines.append("")
    lines.append("## Active lanes touching this area")
    lines.append("")
    if not lanes:
        lines.append("- (no live task worktrees recorded)")
    else:
        for lane in lanes:
            proj = proj_label(lane["project"])
            if lane["err"]:
                lines.append("- {} ({}): unreadable ({})".format(lane["id"], proj, lane["err"]))
            elif not lane["files"]:
                lines.append("- {} ({}): no changes vs {}".format(lane["id"], proj, lane["base"]))
            else:
                dirs = ", ".join(lane["dirs"][:6]) + (" ..." if len(lane["dirs"]) > 6 else "")
                lines.append("- {} ({}): {} ({} files vs {})".format(
                    lane["id"], proj, dirs, len(lane["files"]), lane["base"]))
        for pair in pairs:
            seg = []
            if pair["dirs"]:
                seg.append("shared dirs: " + ", ".join(pair["dirs"][:4]))
            if pair["files"]:
                seg.append("shared files: " + ", ".join(pair["files"][:5])
                           + (" (+{} more)".format(len(pair["files"]) - 5) if len(pair["files"]) > 5 else ""))
            lines.append("- OVERLAP {} + {}: {}".format(pair["a"], pair["b"], "; ".join(seg)))
        if skipped:
            lines.append("- (+{} more lane(s) not probed; raise FM_KNOWLEDGE_OVERLAP_MAX_LANES)".format(skipped))
    lines.append("")
    return "\n".join(lines)


def write_board(text):
    tmp = BOARD.with_name(".BOARD.md.tmp.{}".format(os.getpid()))
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, BOARD)


def render_and_write(project_filter=None):
    lanes, pairs, skipped = probe_lanes()
    now = utcnow()
    with locked():
        entries, tomb = fold()
        board = build_board(entries, tomb, now, lanes, pairs, skipped, None)
        write_board(board)
    if project_filter:
        shown = {eid: e for eid, e in entries.items()
                 if project_matches(e.get("project", ""), project_filter)}
        print(build_board(shown, tomb, now, lanes, pairs, skipped, project_filter))
    else:
        print(board)


# --- commands -----------------------------------------------------------------

def cmd_add(a):
    for field in ("project", "title", "source", "evidence"):
        v = getattr(a, field)
        if "\n" in v or "\r" in v:
            die("--{} must be a single line".format(field))
    if not a.title.strip():
        die("--title must not be empty")
    if not a.body.strip():
        die("--body must not be empty")
    ttl = a.ttl_days if a.ttl_days is not None else DEFAULT_TTL[a.kind]
    if ttl <= 0:
        die("--ttl-days must be a positive integer (got {})".format(a.ttl_days))
    tags = [t.strip().lower() for t in a.tags.split(",") if t.strip()]
    scan_secrets("project", a.project)
    scan_secrets("title", a.title)
    scan_secrets("body", a.body)
    scan_secrets("evidence", a.evidence)
    for t in tags:
        scan_secrets("tags", t)
    now = utcnow()
    lanes, pairs, skipped = probe_lanes()
    with locked():
        entries, tomb = fold()
        for _ in range(10):
            eid = "k-{}-{}".format(now.strftime("%Y%m%d"), secrets.token_hex(3))
            if eid not in entries:
                break
        else:
            die("could not allocate a unique entry id; try again")
        entry = {
            "op": "add",
            "id": eid,
            "project": a.project,
            "kind": a.kind,
            "title": a.title.strip(),
            "body": a.body,
            "tags": tags,
            "source": a.source,
            "evidence": a.evidence,
            "created_at": iso(now),
            "confirmed_at": iso(now),
            "ttl_days": ttl,
            "expires_at": iso(now + timedelta(days=ttl)),
        }
        append_op(entry)
        entries, tomb = fold()
        write_board(build_board(entries, tomb, now, lanes, pairs, skipped))
    print("added {} (kind={} project={} source={} expires {})".format(
        entry["id"], entry["kind"], entry["project"], entry["source"], entry["expires_at"]))


def cmd_list(a):
    entries, tomb = fold()
    now = utcnow()
    rows = []
    for e in entries.values():
        state = entry_state(e, now, tomb)
        if state == "deleted":
            continue
        if state == "expired" and not a.include_expired:
            continue
        if a.project and not project_matches(e.get("project", ""), a.project):
            continue
        if a.kind and e.get("kind") != a.kind:
            continue
        rows.append((e, state))
    rows.sort(key=lambda r: (r[0].get("project", ""), KIND_ORDER.get(r[0].get("kind"), 99),
                             r[0].get("created_at", ""), r[0].get("id", "")))
    for e, state in rows:
        mark = " (EXPIRED)" if state == "expired" else ""
        print("{} [{}] ({}) expires {} - {}{}".format(
            e["id"], e.get("kind", "?"), e.get("project", "?"),
            str(e.get("expires_at", "?"))[:10], e.get("title", ""), mark))
    if not rows:
        print("(no matching entries)")


def cmd_search(a):
    entries, tomb = fold()
    now = utcnow()
    q = a.query.lower()
    hits = []
    for e in entries.values():
        if not is_live(e, now, tomb):
            continue
        if a.project and not project_matches(e.get("project", ""), a.project):
            continue
        hay = "\n".join([e.get("title", ""), e.get("body", ""), " ".join(e.get("tags", []))]).lower()
        if q in hay:
            hits.append(e)
    hits.sort(key=lambda e: (e.get("project", ""), KIND_ORDER.get(e.get("kind"), 99), e.get("id", "")))
    for e in hits:
        print("{} [{}] ({}) expires {} - {}".format(
            e["id"], e.get("kind", "?"), e.get("project", "?"),
            str(e.get("expires_at", "?"))[:10], e.get("title", "")))
    if not hits:
        print("(no matching entries)")


def cmd_confirm(a):
    now = utcnow()
    lanes, pairs, skipped = probe_lanes()
    with locked():
        entries, tomb = fold()
        e = entries.get(a.id)
        if e is None or e["id"] in tomb:
            die("no live or expired entry with id '{}' (unknown or retired)".format(a.id))
        ttl = e.get("ttl_days") or DEFAULT_TTL.get(e.get("kind"), 14)
        rec = {"op": "confirm", "id": e["id"], "at": iso(now),
               "expires_at": iso(now + timedelta(days=ttl))}
        append_op(rec)
        entries, tomb = fold()
        write_board(build_board(entries, tomb, now, lanes, pairs, skipped))
    print("confirmed {} (expires {})".format(e["id"], rec["expires_at"]))


def cmd_delete(a):
    if a.as_who != "firstmate":
        die("delete is firstmate-only: pass --as firstmate (workers never prune the board)")
    now = utcnow()
    lanes, pairs, skipped = probe_lanes()
    with locked():
        entries, tomb = fold()
        e = entries.get(a.id)
        if e is None or e["id"] in tomb:
            die("no entry with id '{}' (unknown or already retired)".format(a.id))
        append_op({"op": "delete", "id": e["id"], "at": iso(now), "by": a.as_who})
        entries, tomb = fold()
        write_board(build_board(entries, tomb, now, lanes, pairs, skipped))
    print("deleted {}".format(a.id))


def cmd_expire(a):
    now = utcnow()
    lanes, pairs, skipped = probe_lanes()
    with locked():
        entries, tomb = fold()
        stale = [e for e in entries.values() if is_stale(e, now, tomb)]
        for e in stale:
            append_op({"op": "expire", "id": e["id"], "at": iso(now)})
        entries, tomb = fold()
        write_board(build_board(entries, tomb, now, lanes, pairs, skipped))
    if stale:
        print("expired {}: {}".format(
            len(stale), " ".join(sorted(e["id"] for e in stale))))
    else:
        print("no entries due for expiry")


def cmd_render(a):
    render_and_write(a.project)


def cmd_overlaps(a):
    lanes, pairs, skipped = probe_lanes()
    if not lanes:
        print("(no live task worktrees recorded)")
    for lane in lanes:
        proj = proj_label(lane["project"])
        if lane["err"]:
            print("lane {} ({}): unreadable ({})".format(lane["id"], proj, lane["err"]))
        elif not lane["files"]:
            print("lane {} ({}): no changes vs {}".format(lane["id"], proj, lane["base"]))
        else:
            dirs = ", ".join(lane["dirs"][:6]) + (" ..." if len(lane["dirs"]) > 6 else "")
            print("lane {} ({}): {} files vs {} (top dirs: {})".format(
                lane["id"], proj, len(lane["files"]), lane["base"], dirs))
    if not pairs:
        print("no overlapping lanes")
    for pair in pairs:
        seg = []
        if pair["dirs"]:
            seg.append("shared top-level dirs: " + ", ".join(pair["dirs"][:6]))
        if pair["files"]:
            seg.append("shared files: " + ", ".join(pair["files"][:5])
                       + (" (+{} more)".format(len(pair["files"]) - 5) if len(pair["files"]) > 5 else ""))
        print("overlap {} + {}: {}".format(pair["a"], pair["b"], "; ".join(seg)))
    if skipped:
        print("(+{} more lane(s) not probed; raise FM_KNOWLEDGE_OVERLAP_MAX_LANES)".format(skipped))


def cmd_digest(_a):
    entries, tomb = fold()
    now = utcnow()
    live = [e for e in entries.values() if is_live(e, now, tomb)]
    stale_n = sum(1 for e in entries.values() if is_stale(e, now, tomb))
    lines = []
    projs = {}
    for e in live:
        projs.setdefault(e.get("project") or "fleet", []).append(e)
    lines.append("Knowledge board: {} live entries across {} project(s) ({} past expiry, {} retired)".format(
        len(live), len(projs), stale_n, len(tomb)))
    for p in sorted(projs):
        kinds = {}
        for e in projs[p]:
            kinds[e.get("kind", "?")] = kinds.get(e.get("kind", "?"), 0) + 1
        lines.append("  {}: {} ({})".format(
            p, len(projs[p]),
            ", ".join("{} {}{}".format(n, k, "s" if n != 1 else "") for k, n in sorted(kinds.items()))))
    soon = [e for e in live if parse_ts(e.get("expires_at")) and
            parse_ts(e["expires_at"]) - now <= timedelta(hours=24)]
    soon.sort(key=lambda e: e["expires_at"])
    if soon:
        lines.append("Expiring within 24h:")
        for e in soon[:3]:
            lines.append("  {} \"{}\" ({}/{}) expires {} - confirm to renew".format(
                e["id"], e.get("title", ""), e.get("project", "?"), e.get("kind", "?"),
                e.get("expires_at", "?")))
        if len(soon) > 3:
            lines.append("  (+{} more)".format(len(soon) - 3))
    lanes, pairs, skipped = probe_lanes()
    if pairs:
        lines.append("Active lane overlaps:")
        for pair in pairs[:3]:
            seg = []
            if pair["dirs"]:
                seg.append("dirs " + ", ".join(pair["dirs"][:3]))
            if pair["files"]:
                seg.append("files " + ", ".join(pair["files"][:3])
                           + (" (+{} more)".format(len(pair["files"]) - 3) if len(pair["files"]) > 3 else ""))
            lines.append("  {} + {}: {}".format(pair["a"], pair["b"], "; ".join(seg)))
        if len(pairs) > 3:
            lines.append("  (+{} more pair(s))".format(len(pairs) - 3))
    peer = recent_peer_lines(3)
    if peer:
        lines.append("Recent peer traffic:")
        lines.extend("  " + ln for ln in peer)
    if len(lines) > DIGEST_LINE_CAP:
        lines = lines[:DIGEST_LINE_CAP - 1] + [
            "(digest capped; run bin/fm-knowledge.sh list / overlaps for the rest)"]
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(
        prog="fm-knowledge.sh",
        description="Fleet knowledge board; the full contract lives in docs/crew-knowledge.md.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("add", help="append a knowledge entry")
    pa.add_argument("--project", required=True)
    pa.add_argument("--kind", required=True, choices=KINDS)
    pa.add_argument("--title", required=True)
    pa.add_argument("--body", required=True)
    pa.add_argument("--tags", default="")
    pa.add_argument("--source", default="firstmate")
    pa.add_argument("--evidence", default="")
    pa.add_argument("--ttl-days", type=int, default=None)
    pl = sub.add_parser("list")
    pl.add_argument("--project")
    pl.add_argument("--kind", choices=KINDS)
    pl.add_argument("--include-expired", action="store_true")
    ps = sub.add_parser("search")
    ps.add_argument("query")
    ps.add_argument("--project")
    pc = sub.add_parser("confirm")
    pc.add_argument("id")
    pd = sub.add_parser("delete")
    pd.add_argument("id")
    pd.add_argument("--as", dest="as_who", required=True)
    sub.add_parser("expire")
    pr = sub.add_parser("render")
    pr.add_argument("--project")
    sub.add_parser("overlaps")
    sub.add_parser("digest")
    args = ap.parse_args(sys.argv[1:])
    if not STATE.is_dir():
        die("state dir '{}' is missing; set FM_HOME to a firstmate home".format(STATE))
    {"add": cmd_add, "list": cmd_list, "search": cmd_search, "confirm": cmd_confirm,
     "delete": cmd_delete, "expire": cmd_expire, "render": cmd_render,
     "overlaps": cmd_overlaps, "digest": cmd_digest}[args.cmd](args)


main()
FM_KNOWLEDGE_PY
