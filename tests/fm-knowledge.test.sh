#!/usr/bin/env bash
# tests/fm-knowledge.test.sh - the fleet knowledge board (bin/fm-knowledge.sh).
#
# The board is an append-only event log (state/knowledge/entries.jsonl) folded
# on every read, with BOARD.md rendered atomically on each mutation and per-kind
# TTLs (fact/hazard 14d, recipe 60d, overlap 3d). These tests drive the real
# script against a temp FM_HOME and pin:
#   1. add assigns a k-<yyyymmdd>-<6hex> id, records provenance fields, applies
#      the per-kind TTL default, and renders BOARD.md.
#   2. list/search filter by project and kind; search matches body text.
#   3. Secret-shaped bodies are refused; the refusal names the pattern class,
#      never the matched text.
#   4. confirm re-arms an entry; delete requires --as firstmate and tombstones.
#   5. expire retires past-TTL entries exactly once (idempotent second run).
#   6. A corrupt log line warns on stderr but never breaks the fold.
#   7. render --project scopes stdout while BOARD.md always holds the full board.
#   8. digest stays under 20 lines and folds in peer traffic when present.
# Contract: docs/crew-knowledge.md.
set -u

# shellcheck source=tests/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

KNOW="$ROOT/bin/fm-knowledge.sh"

TMP_ROOT=$(fm_test_tmproot fm-knowledge)
TMP_ROOT=$(cd "$TMP_ROOT" && pwd)

setup_home() {  # <name> -> echoes home dir with state/ data/ config/
  local dir="$TMP_ROOT/$1"
  mkdir -p "$dir/state" "$dir/data" "$dir/config"
  printf '%s\n' "$dir"
}

jsonl_field() {  # <jsonl-file> <line-no> <field>
  sed -n "${2}p" "$1" | python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["'"$3"'"])'
}

test_add_records_provenance_and_ttl() {
  local home out id rc
  home=$(setup_home add)
  out=$(FM_HOME="$home" "$KNOW" add --project alpha --kind fact --title "Billing freeze" \
    --body "No billing deploys on Friday." --tags "deploy,billing" --source fm-lane-a \
    --evidence "src/api.c:42" 2>&1); rc=$?
  expect_code 0 "$rc" "a well-formed add should succeed"
  assert_contains "$out" "added k-" "add should print the assigned id"
  id=$(printf '%s' "$out" | sed -n 's/^added \(k-[0-9a-f-]*\) .*/\1/p')
  case "$id" in k-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-??????) : ;; *) fail "id shape wrong: $id" ;; esac
  [ -f "$home/state/knowledge/entries.jsonl" ] || fail "add did not append to entries.jsonl"
  [ -f "$home/state/knowledge/BOARD.md" ] || fail "add did not render BOARD.md"
  [ "$(jsonl_field "$home/state/knowledge/entries.jsonl" 1 ttl_days)" = 14 ] \
    || fail "fact TTL default should be 14 days"
  [ "$(jsonl_field "$home/state/knowledge/entries.jsonl" 1 source)" = "fm-lane-a" ] \
    || fail "provenance source not recorded"
  [ "$(jsonl_field "$home/state/knowledge/entries.jsonl" 1 evidence)" = "src/api.c:42" ] \
    || fail "evidence not recorded"
  FM_HOME="$home" "$KNOW" add --project alpha --kind recipe --title "R" --body "b" >/dev/null
  FM_HOME="$home" "$KNOW" add --project alpha --kind overlap --title "O" --body "b" >/dev/null
  [ "$(jsonl_field "$home/state/knowledge/entries.jsonl" 2 ttl_days)" = 60 ] \
    || fail "recipe TTL default should be 60 days"
  [ "$(jsonl_field "$home/state/knowledge/entries.jsonl" 3 ttl_days)" = 3 ] \
    || fail "overlap TTL default should be 3 days"
  pass "knowledge add: id shape, provenance, per-kind TTL defaults, board render"
}

test_list_search_and_project_filter() {
  local home out
  home=$(setup_home list)
  FM_HOME="$home" "$KNOW" add --project alpha --kind fact --title "Alpha fact" --body "alpha body needleword" >/dev/null
  FM_HOME="$home" "$KNOW" add --project beta --kind hazard --title "Beta hazard" --body "beta body" >/dev/null
  out=$(FM_HOME="$home" "$KNOW" list --project alpha)
  assert_contains "$out" "Alpha fact" "project filter should keep the alpha entry"
  case "$out" in *"Beta hazard"*) fail "project filter leaked the beta entry" ;; esac
  out=$(FM_HOME="$home" "$KNOW" search needleword)
  assert_contains "$out" "Alpha fact" "search should match body text"
  out=$(FM_HOME="$home" "$KNOW" search needleword --project beta)
  case "$out" in *"Alpha fact"*) fail "scoped search leaked across projects" ;; esac
  out=$(FM_HOME="$home" "$KNOW" list --kind hazard)
  assert_contains "$out" "Beta hazard" "kind filter should keep the hazard"
  case "$out" in *"Alpha fact"*) fail "kind filter leaked the fact" ;; esac
  pass "knowledge list/search: project and kind filters hold"
}

test_secret_rejection() {
  local home err rc
  home=$(setup_home secret); err="$home/err"
  FM_HOME="$home" "$KNOW" add --project alpha --kind fact --title "creds" \
    --body "api_key = sk-abc123def456ghi789jkl0" >/dev/null 2>"$err"; rc=$?
  expect_code 1 "$rc" "a secret-shaped body must be refused"
  assert_contains "$(cat "$err")" "never carry secrets" "the refusal should teach the pointer rule"
  case "$(cat "$err")" in
    *sk-abc123*) fail "the refusal must never echo the matched secret" ;;
  esac
  [ ! -s "$home/state/knowledge/entries.jsonl" ] || fail "a refused entry must not reach the log"
  FM_HOME="$home" "$KNOW" add --project alpha --kind fact --title "pk" \
    --body "-----BEGIN PRIVATE KEY-----" >/dev/null 2>"$err"; rc=$?
  expect_code 1 "$rc" "private key blocks are refused"
  FM_HOME="$home" "$KNOW" add --project alpha --kind fact --title "tok" \
    --body "ghp_0123456789abcdef0123456789abcdef0123" >/dev/null 2>"$err"; rc=$?
  expect_code 1 "$rc" "GitHub tokens are refused"
  pass "knowledge add: secret patterns refused without echoing the secret"
}

test_confirm_delete_expire_lifecycle() {
  local home id rc err
  home=$(setup_home lifecycle); err="$home/err"
  FM_HOME="$home" "$KNOW" add --project alpha --kind fact --title "F" --body "b" >/dev/null
  id=$(jsonl_field "$home/state/knowledge/entries.jsonl" 1 id)
  FM_HOME="$home" "$KNOW" confirm "$id" >/dev/null 2>"$err" || fail "confirm failed: $(cat "$err")"
  FM_HOME="$home" "$KNOW" confirm k-nope-nope >/dev/null 2>"$err"; rc=$?
  expect_code 1 "$rc" "confirming an unknown id must fail"
  FM_HOME="$home" "$KNOW" delete "$id" --as worker >/dev/null 2>"$err"; rc=$?
  expect_code 1 "$rc" "a worker delete must be refused"
  assert_contains "$(cat "$err")" "firstmate-only" "the refusal should name the firstmate gate"
  FM_HOME="$home" "$KNOW" delete "$id" --as firstmate >/dev/null 2>"$err" || fail "firstmate delete failed"
  FM_HOME="$home" "$KNOW" delete "$id" --as firstmate >/dev/null 2>"$err"; rc=$?
  expect_code 1 "$rc" "deleting a retired entry must fail"
  case "$(FM_HOME="$home" "$KNOW" list)" in *"$id"*) fail "a deleted entry still lists as live" ;; esac
  pass "knowledge lifecycle: confirm renews, delete is firstmate-only and tombstones"
}

test_expire_is_idempotent() {
  local home id out
  home=$(setup_home expire)
  FM_HOME="$home" "$KNOW" add --project alpha --kind fact --title "F" --body "b" >/dev/null
  id=$(jsonl_field "$home/state/knowledge/entries.jsonl" 1 id)
  # Backdate the entry past its TTL by rewriting the log (firstmate-only surgery).
  python3 - "$home/state/knowledge/entries.jsonl" <<PY
import json, sys
p = sys.argv[1]
lines = [json.loads(l) for l in open(p) if l.strip()]
for rec in lines:
    if rec.get("id") == "$id":
        rec["expires_at"] = "2000-01-01T00:00:00Z"
open(p, "w").write("".join(json.dumps(r) + "\n" for r in lines))
PY
  out=$(FM_HOME="$home" "$KNOW" expire)
  assert_contains "$out" "expired 1: $id" "expire should retire the past-TTL entry"
  case "$(FM_HOME="$home" "$KNOW" list)" in *"$id"*) fail "an expired entry still lists live" ;; esac
  out=$(FM_HOME="$home" "$KNOW" expire)
  assert_contains "$out" "no entries due" "a second expire pass is a no-op (idempotent)"
  pass "knowledge expire: past-TTL entries retire exactly once"
}

test_corrupt_line_warns_but_reads() {
  local home out err rc
  home=$(setup_home corrupt); err="$home/err"
  FM_HOME="$home" "$KNOW" add --project alpha --kind fact --title "Good" --body "b" >/dev/null
  printf 'not-json!!\n' >> "$home/state/knowledge/entries.jsonl"
  out=$(FM_HOME="$home" "$KNOW" list 2>"$err"); rc=$?
  expect_code 0 "$rc" "a corrupt line must not break the fold"
  assert_contains "$out" "Good" "valid entries still list"
  assert_contains "$(cat "$err")" "unparseable log line skipped" "the corruption should be named on stderr"
  pass "knowledge fold: a corrupt line warns and is skipped"
}

test_render_scopes_stdout_board_stays_full() {
  local home out
  home=$(setup_home render)
  FM_HOME="$home" "$KNOW" add --project alpha --kind fact --title "A entry" --body "b" >/dev/null
  FM_HOME="$home" "$KNOW" add --project beta --kind fact --title "B entry" --body "b" >/dev/null
  out=$(FM_HOME="$home" "$KNOW" render --project alpha)
  assert_contains "$out" "A entry" "render --project alpha should show the alpha entry"
  case "$out" in *"B entry"*) fail "render --project alpha leaked the beta entry to stdout" ;; esac
  assert_contains "$(cat "$home/state/knowledge/BOARD.md")" "B entry" \
    "BOARD.md must always hold the full board, regardless of stdout scoping"
  pass "knowledge render: stdout is project-scoped, BOARD.md stays complete"
}

test_digest_is_bounded_and_includes_peers() {
  local home lines out
  home=$(setup_home digest)
  FM_HOME="$home" "$KNOW" add --project alpha --kind fact --title "F" --body "b" >/dev/null
  printf '2026-09-16T10:00:00Z fm-lane-a -> fm-lane-b [seq 001] test line\n' > "$home/state/fm-lane-a.peer.log"
  out=$(FM_HOME="$home" "$KNOW" digest)
  assert_contains "$out" "Knowledge board:" "digest header"
  assert_contains "$out" "Recent peer traffic:" "digest should fold in peer traffic"
  lines=$(printf '%s\n' "$out" | wc -l | tr -d ' ')
  [ "$lines" -le 19 ] || fail "digest must stay under 20 lines, got $lines"
  pass "knowledge digest: bounded and carries peer traffic"
}

test_add_records_provenance_and_ttl
test_list_search_and_project_filter
test_secret_rejection
test_confirm_delete_expire_lifecycle
test_expire_is_idempotent
test_corrupt_line_warns_but_reads
test_render_scopes_stdout_board_stays_full
test_digest_is_bounded_and_includes_peers
