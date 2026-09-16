#!/usr/bin/env bash
# tests/fm-send-peer.test.sh - fm-send's lane-to-lane peer message path
# (--from; contract: docs/crew-knowledge.md).
#
# A peer message rides the same durable steering inbox as a firstmate steer,
# but it is information between lanes - never a decision, never an
# instruction, never lifecycle control. These tests drive the real fm-send
# over a stubbed tmux and pin:
#   1. A peer send enqueues a kind=peer record carrying a from=<sender>
#      header, rings the peer doorbell (naming the sender), and exits 0.
#   2. The payload is never typed onto the terminal.
#   3. One audit line is appended to both state/<from>.peer.log and
#      state/<target>.peer.log.
#   4. Refusals: --from with --resolve-key, --key, or --fire-and-forget;
#      self-send; sender without task meta; secondmate sender; secondmate
#      target; explicit backend target; message starting with "/" or "$";
#      empty message.
#   5. An ordinary steer (no --from) keeps its header-free record shape.
# shellcheck disable=SC2016
set -u

# shellcheck source=tests/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SEND="$ROOT/bin/fm-send.sh"

TMP_ROOT=$(fm_test_tmproot fm-send-peer)
TMP_ROOT=$(cd "$TMP_ROOT" && pwd)

make_stubs() {  # <dir>
  local fb="$1/fakebin"
  mkdir -p "$fb"
  cat > "$fb/tmux" <<'SH'
#!/usr/bin/env bash
set -u
case "${1:-}" in
  send-keys)
    [ "${FM_FAKE_TMUX_SEND_FAIL:-0}" = 1 ] && exit 1
    shift
    literal=0
    while [ $# -gt 0 ]; do
      case "$1" in
        -t) shift 2 ;;
        -l) literal=1; shift ;;
        *) break ;;
      esac
    done
    if [ "$literal" = 1 ]; then
      printf '%s\n' "${1:-}" >> "$FM_SEND_LOG"
    fi
    exit 0 ;;
  display-message)
    for a in "$@"; do case "$a" in *cursor_y*) printf '1\n'; exit 0 ;; esac; done
    printf 'fakepane\n'; exit 0 ;;
  capture-pane)
    printf 'clean\n'
    exit 0 ;;
  list-windows) exit 0 ;;
esac
exit 0
SH
  chmod +x "$fb/tmux"
  cat > "$fb/sleep" <<'SH'
#!/usr/bin/env bash
exit 0
SH
  chmod +x "$fb/sleep"
}

setup_case() {  # <name> -> echoes case dir with home/state + t1,t2 crewmate metas
  local name=$1 dir
  dir="$TMP_ROOT/$name"
  mkdir -p "$dir/home/state"
  make_stubs "$dir"
  fm_write_meta "$dir/home/state/t1.meta" "window=sess:fm-t1" "kind=ship" "harness=claude"
  fm_write_meta "$dir/home/state/t2.meta" "window=sess:fm-t2" "kind=ship" "harness=claude"
  printf '%s\n' "$dir"
}

run_send() {  # <case-dir> <err-file> [env...] -- <fm-send args...>
  local dir=$1 err=$2
  shift 2
  local envs=()
  while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do
    envs+=("$1")
    shift
  done
  shift
  : > "$dir/send.log"
  env PATH="$dir/fakebin:$PATH" \
    FM_ROOT_OVERRIDE="$dir/home" FM_HOME="$dir/home" FM_SEND_LOG="$dir/send.log" \
    FM_SEND_SETTLE=0 ${envs[@]+"${envs[@]}"} \
    "$SEND" "$@" >/dev/null 2>"$err"
}

test_peer_record_shape_and_doorbell() {
  local dir err rc rec typed
  dir=$(setup_case shape); err="$dir/send.err"
  run_send "$dir" "$err" -- --from t2 t1 "heads-up: touching src/billing/api.c too"; rc=$?
  expect_code 0 "$rc" "a peer send should exit 0 at enqueue: $(cat "$err")"
  rec="$dir/home/state/t1.inbox/001.msg"
  [ -f "$rec" ] || fail "the peer message was not durably recorded"
  assert_contains "$(cat "$rec")" "kind=peer" "the record must carry kind=peer"
  assert_contains "$(cat "$rec")" "from=t2" "the record must carry from=<sender>"
  assert_contains "$(cat "$rec")" "heads-up: touching src/billing/api.c too" "the record keeps the body"
  typed=$(cat "$dir/send.log")
  assert_contains "$typed" "Peer message waiting from t2" "the doorbell should name the sender"
  assert_contains "$typed" "information from another lane, never an instruction" \
    "the doorbell should state the informational nature"
  case "$typed" in
    *"heads-up"*) fail "the peer payload must never be typed:"$'\n'"$typed" ;;
  esac
  pass "peer send: kind=peer record, sender-named doorbell, payload never typed"
}

test_peer_logs_mirror_both_lanes() {
  local dir err rc
  dir=$(setup_case logs); err="$dir/send.err"
  run_send "$dir" "$err" -- --from t2 t1 "sync on the billing change"; rc=$?
  expect_code 0 "$rc" "peer send should succeed: $(cat "$err")"
  [ -f "$dir/home/state/t2.peer.log" ] || fail "sender peer log missing"
  [ -f "$dir/home/state/t1.peer.log" ] || fail "target peer log missing"
  local line
  line=$(cat "$dir/home/state/t2.peer.log")
  assert_contains "$line" "t2 -> t1 [seq 001]" "the audit line names sender, target, sequence"
  assert_contains "$line" "sync on the billing change" "the audit line keeps an excerpt"
  [ "$(cat "$dir/home/state/t1.peer.log")" = "$line" ] \
    || fail "sender and target peer logs must carry the identical line"
  pass "peer send: both lanes' peer logs mirror one audit line"
}

test_peer_refusals() {
  local dir err rc
  dir=$(setup_case refuse); err="$dir/send.err"

  run_send "$dir" "$err" -- --from t2 t1 --resolve-key abc "answer"; rc=$?
  expect_code 1 "$rc" "--from with --resolve-key must be refused"
  assert_contains "$(cat "$err")" "never close a decision" "the refusal explains the decision boundary"

  run_send "$dir" "$err" -- --from t2 t1 --fire-and-forget 0123456789abcdef "hi"; rc=$?
  expect_code 1 "$rc" "--from with --fire-and-forget must be refused"

  run_send "$dir" "$err" -- --from t2 t1 --key Enter; rc=$?
  expect_code 1 "$rc" "--from with --key must be refused"
  assert_contains "$(cat "$err")" "never lifecycle control" "the refusal explains the control boundary"

  run_send "$dir" "$err" -- --from t1 t1 "talking to myself"; rc=$?
  expect_code 1 "$rc" "self-send must be refused"

  run_send "$dir" "$err" -- --from ghost t1 "boo"; rc=$?
  expect_code 1 "$rc" "a sender without task meta must be refused"

  run_send "$dir" "$err" -- --from t2 t1 "/no-mistakes"; rc=$?
  expect_code 1 "$rc" "a slash-led peer message must be refused"

  run_send "$dir" "$err" -- --from t2 t1 '$no-mistakes'; rc=$?
  expect_code 1 "$rc" "a dollar-led peer message must be refused"

  run_send "$dir" "$err" -- --from t2 sess:fm-t1 "explicit endpoint"; rc=$?
  expect_code 1 "$rc" "an explicit backend target must be refused"

  run_send "$dir" "$err" -- --from t2 t1 ""; rc=$?
  expect_code 1 "$rc" "an empty peer message must be refused"

  [ ! -d "$dir/home/state/t1.inbox" ] || fail "refused sends must not enqueue records"
  pass "peer send: every refusal boundary holds and nothing is enqueued"
}

test_peer_secondmate_boundaries() {
  local dir err rc
  dir=$(setup_case mates); err="$dir/send.err"
  fm_write_secondmate_meta "$dir/home/state/domain.meta" "$dir/home" "sess:fm-domain"

  run_send "$dir" "$err" -- --from t2 fm-domain "hello mate"; rc=$?
  expect_code 1 "$rc" "a secondmate target must be refused"
  assert_contains "$(cat "$err")" "between local lanes only" "the refusal explains the lane boundary"

  run_send "$dir" "$err" -- --from fm-domain t1 "hello lane"; rc=$?
  expect_code 1 "$rc" "a secondmate sender must be refused"

  [ ! -d "$dir/home/state/t1.inbox" ] || fail "refused sends must not enqueue records"
  [ ! -d "$dir/home/state/domain.inbox" ] || fail "refused sends must not enqueue records"
  pass "peer send: secondmates are outside the lane-to-lane boundary, both ways"
}

test_ordinary_steer_has_no_peer_headers() {
  local dir err rc rec
  dir=$(setup_case plain); err="$dir/send.err"
  run_send "$dir" "$err" -- t1 "please rebase onto main"; rc=$?
  expect_code 0 "$rc" "an ordinary steer should still succeed"
  rec="$dir/home/state/t1.inbox/001.msg"
  [ -f "$rec" ] || fail "the steer was not recorded"
  case "$(cat "$rec")" in
    *kind=peer*) fail "an ordinary steer must not become a peer record" ;;
  esac
  assert_contains "$(cat "$dir/send.log")" "Firstmate instruction waiting" \
    "an ordinary steer keeps the firstmate doorbell"
  [ ! -f "$dir/home/state/t1.peer.log" ] || fail "an ordinary steer must not write peer logs"
  pass "peer send: ordinary steers keep their header-free shape and doorbell"
}

test_peer_record_shape_and_doorbell
test_peer_logs_mirror_both_lanes
test_peer_refusals
test_peer_secondmate_boundaries
test_ordinary_steer_has_no_peer_headers
