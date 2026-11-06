#!/usr/bin/env bash
# Behavior tests for the generic process-to-event runner and its Lavish adapter.
#
# The source under test is a fake blocking process that returns only when its
# trigger file appears, so completion is a real process event and no test here
# depends on a discovery timer. The Lavish adapter is exercised through its own
# public commands against the currently published poll shape; no live Lavish
# server is started.
#
# Delivery is deliberately NOT asserted as at-least-once or lossless: the
# published Lavish poll clears feedback destructively before returning it, so
# the only durability under test is the runner's own - output that reached the
# runner is stored before it is announced.
set -u

# shellcheck source=tests/lib.sh
. "~/.no-mistakes/worktrees/fe3685018ca6/01M6R755KVVTJ6CP2E7GWWY5VR/tests/lib.sh"

ROOT="~/.no-mistakes/worktrees/fe3685018ca6/01M6R755KVVTJ6CP2E7GWWY5VR"
TMP_ROOT=$(fm_test_tmproot fm-procevent-tests)
export FM_PROCEVENT_CLAIM_ROOT="$TMP_ROOT/claims"
export LAVISH_AXI_STATE_DIR="$TMP_ROOT/lavish-state"
mkdir -p "$LAVISH_AXI_STATE_DIR"

# Lavish owns this persisted session contract. The fake CLI fixtures exercise
# its published poll and synchronous reply command boundaries without starting a server.
lavish_session() {  # <artifact> [session-url]
  perl -MJSON::PP -MCwd=realpath -MDigest::SHA=sha256_hex -MEncode=decode -e '
    my ($path, $artifact, $url) = @ARGV;
    my $real = realpath($artifact) // die "missing fixture artifact";
    my $key = substr(sha256_hex($real), 0, 16);
    my $state = { sessions => {} };
    if (-f $path) { open my $in, "<", $path or die $!; local $/; $state = decode_json(<$in>); }
    $state->{sessions}{$key} = {
      key => $key, file => decode("UTF-8", $real), status => "open", url => $url,
    };
    open my $out, ">", $path or die $!;
    print $out encode_json($state);
  ' "$LAVISH_AXI_STATE_DIR/state.json" "$1" "${2:-http://127.0.0.1:14387/session/0123456789abcdef}"
}

BLOCKER="$TMP_ROOT/blocker.sh"
cat > "$BLOCKER" <<'SH'
#!/usr/bin/env bash
# Blocks until the trigger exists, then emits its payload. Completion is the
# event; nothing here polls on a schedule. The wait is bounded so a stub that
# escapes its test cannot keep spawning processes indefinitely.
trigger=$1; shift
while [ ! -e "$trigger" ]; do
  [ "$SECONDS" -lt "${FM_TEST_STUB_MAX_BLOCK_SECONDS:-120}" ] || exit 75
  sleep 0.05
done
[ -n "${BLOCKER_STDERR:-}" ] && printf 'noise on stderr\n' >&2
[ -n "${BLOCKER_EXIT:-}" ] && exit "$BLOCKER_EXIT"
printf '%s\n' "$@"
SH
chmod +x "$BLOCKER"

# Records that the wrapped command actually started, then becomes it. A claim
# only proves its runner got as far as claiming; a test that needs the runner
# already inside its source command waits for this marker instead of a settle
# window, because a runner still short of that command retires itself when its
# registration goes away.
STARTED_BLOCKER="$TMP_ROOT/started-blocker.sh"
cat > "$STARTED_BLOCKER" <<'SH'
#!/usr/bin/env bash
printf 'started\n' > "$1"
shift
exec "$@"
SH
chmod +x "$STARTED_BLOCKER"

pe() { FM_HOME="$1" "$ROOT/bin/fm-procevent.sh" "${@:2}"; }

# Every home this suite registers a source in is tracked so teardown can stop
# its runners. A runner started by reconcile is detached and reparented, so a
# source that never completes outlives the suite unless its home is swept -
# removing the fixture directory does not stop an already-running child.
# tests/lib.sh owns that sweep and runs it from every cleanup path.
pe_register() {  # <home> <adapter> <source-id> -- <argv>...
  local home=$1 adapter=$2 id=$3
  shift 3
  fm_test_track_procevent_home "$home"
  pe "$home" register "$adapter" "$id" "$@"
}
new_home() { mkdir -p "$1/state"; }
# A worker-owned board can only be armed for a task whose endpoint metadata the
# runner can ring, so every fixture worker needs the same durable record a real
# spawn leaves behind.
new_task_endpoint() {  # <home> <task-id>
  mkdir -p "$1/state"
  printf 'window=fmtest:fm-%s\nworktree=%s/worktree-%s\nproject=fmtest\n' "$2" "$1" "$2" \
    > "$1/state/$2.meta"
}
wake_payloads() { awk -F '\t' '{print $5}' "$1/state/.wake-queue" 2>/dev/null; }

# The wake queue is a durable tab-separated record firstmate consumes:
# <epoch> <sequence> <kind> <key> <payload>. These read the rows reconcile
# publishes for a source it stranded, keyed by that source and its claim
# generation.
stranded_wake_keys() {  # <home> <source-id>
  [ -e "$1/state/.wake-queue" ] || return 0
  awk -F '\t' -v id="$2" \
    '$3 == "check" && index($4, "procevent:" id ":stranded:") == 1 { print $4 }' \
    "$1/state/.wake-queue"
}
stranded_wake_count() {  # <home> <source-id>
  stranded_wake_keys "$1" "$2" | grep -c . || true
}
stranded_wake_payloads() {  # <home> <source-id>
  [ -e "$1/state/.wake-queue" ] || return 0
  awk -F '\t' -v id="$2" \
    '$3 == "check" && index($4, "procevent:" id ":stranded:") == 1 { print $5 }' \
    "$1/state/.wake-queue"
}
# The same rows for a launch reconcile could not confirm, keyed by that source
# and the registration identity the launch ran under.
launch_failed_wake_keys() {  # <home> <source-id>
  [ -e "$1/state/.wake-queue" ] || return 0
  awk -F '\t' -v id="$2" \
    '$3 == "check" && index($4, "procevent:" id ":launch-failed:") == 1 { print $4 }' \
    "$1/state/.wake-queue"
}
launch_failed_wake_count() {  # <home> <source-id>
  launch_failed_wake_keys "$1" "$2" | grep -c . || true
}
launch_failed_wake_payloads() {  # <home> <source-id>
  [ -e "$1/state/.wake-queue" ] || return 0
  awk -F '\t' -v id="$2" \
    '$3 == "check" && index($4, "procevent:" id ":launch-failed:") == 1 { print $5 }' \
    "$1/state/.wake-queue"
}

first_result() {  # <home> <source-id>: print the first captured result, if any
  local g
  for g in "$1/state/procevent-inbox/$2".*.result; do
    [ -e "$g" ] || continue
    printf '%s\n' "$g"
    return 0
  done
  return 1
}

count_results() {  # <home> <source-id>
  local g n=0
  for g in "$1/state/procevent-inbox/$2".*.result; do
    [ -e "$g" ] && n=$((n + 1))
  done
  printf '%s\n' "$n"
}

wait_for() {  # <file> [tries]
  local f=$1 n=${2:-100}
  for _ in $(seq 1 "$n"); do [ -s "$f" ] && return 0; sleep 0.1; done
  return 1
}

wait_for_lines() {
  local f=$1 want=$2 n=${3:-100} have
  for _ in $(seq 1 "$n"); do
    if [ -f "$f" ]; then
      have=$(wc -l < "$f" | tr -d ' ')
    else
      have=0
    fi
    case "$have" in ''|*[!0-9]*) have=0 ;; esac
    [ "$have" -ge "$want" ] && return 0
    sleep 0.1
  done
  return 1
}

# A worker re-arms as soon as its round is published, which can land while the
# earlier generation's runner is still finishing and holding the claim. The
# Lavish 0.1.80 stand-in records synchronous reply acceptance before its poll.
DRAIN="$TMP_ROOT/draining-rearm"
mkdir -p "$DRAIN/bin" "$DRAIN/home/state"
export DRAIN
cat > "$DRAIN/bin/lavish-axi" <<'SH'
#!/usr/bin/env bash
set -eu
case "${1-}" in
  --version) printf '0.1.80\n' ;;
  reply)
    [ "${3-}" = --agent-reply-file ] || exit 2
    printf '%s\n' "$(cat -- "$4")" >> "$DRAIN/replies"
    printf 'reply\n' >> "$DRAIN/order"
    ;;
  poll)
    printf 'poll\n' >> "$DRAIN/polls"
    printf 'poll\n' >> "$DRAIN/order"
    if [ "$(wc -l < "$DRAIN/polls")" -eq 1 ]; then
      while [ ! -e "$DRAIN/release1" ]; do sleep 0.02; done
    fi
    [ "${3-}" != --agent-reply ] || exit 3
    if [ "$(wc -l < "$DRAIN/polls")" -ge 2 ]; then
      while [ ! -e "$DRAIN/release2" ]; do sleep 0.02; done
    fi
    printf 'session:\n  status: feedback\nprompts[1]{uid,prompt,selector,tag,text}:\n  "","next round","","message",""\n'
    ;;
  *) exit 2 ;;
esac
SH
chmod +x "$DRAIN/bin/lavish-axi"
drain_art="$DRAIN/board.html"
printf '<h1>drain</h1>\n' > "$drain_art"
lavish_session "$drain_art"
drain_id=$("$ROOT/bin/fm-procevent-lavish.sh" source-id "$drain_art")
fm_test_track_procevent_home "$DRAIN/home"
new_task_endpoint "$DRAIN/home" worker-drain
printf 'first drain reply\n' > "$DRAIN/reply1"
printf 'second drain reply\n' > "$DRAIN/reply2"
PATH="$DRAIN/bin:$PATH" FM_HOME="$DRAIN/home" \
  "$ROOT/bin/fm-procevent-lavish.sh" arm "$drain_art" --for worker-drain \
  --agent-reply-file "$DRAIN/reply1" >/dev/null \
  || fail "the first generation of the draining fixture did not arm"
[ "$(cat "$DRAIN/replies" 2>/dev/null || true)" = "first drain reply" ] \
  || fail "arm returned before Lavish accepted its staged reply"
[ "$(head -n 1 "$DRAIN/order")" = reply ] \
  || fail "arm started the long-poll before Lavish accepted the reply"
pass "arm posts and confirms the staged reply before reporting listener readiness"
drain_claim="$FM_PROCEVENT_CLAIM_ROOT/$drain_id.claim"
cp "$drain_claim" "$DRAIN/generation-one.claim"
touch "$DRAIN/release1"
wait_for "$DRAIN/home/state/procevent-inbox/$drain_id.1.result" \
  || fail "the first generation of the draining fixture never captured its round"
for _ in $(seq 1 100); do
  [ -e "$drain_claim" ] || break
  sleep 0.05
done
[ ! -e "$drain_claim" ] || fail "the first generation of the draining fixture never exited"
# Stand the first generation's claim back up on a live process so the re-arm
# meets it still held, then release it partway through the confirm window.
perl -MPOSIX=setsid -e 'setsid() >= 0 or exit 1; exec @ARGV' sleep 60 &
drain_holder=$!
# Read the identity only once the holder has exec'd sleep: mid-exec its cmdline
# can read empty, and a pre-exec identity would never match the live holder.
for _ in $(seq 1 100); do
  case "$(ps -p "$drain_holder" -o comm= 2>/dev/null)" in *sleep) break ;; esac
  sleep 0.05
done
drain_holder_identity=$(bash -c '. "$1/bin/fm-wake-lib.sh"; fm_pid_identity "$2"' _ "$ROOT" "$drain_holder") \
  || fail "could not read the draining holder's identity"
awk -v pid="$drain_holder" -v ident="$drain_holder_identity" \
  'NR == 2 { print pid; next } NR == 4 { print ident; next } { print }' \
  "$DRAIN/generation-one.claim" > "$drain_claim"
chmod 0600 "$drain_claim"
[ "$(pe "$DRAIN/home" list | awk -v id="$drain_id" '$1 == id { print $3 }')" = task:worker-drain/round-open ] \
  || fail "fixture invalid: the stood-up first generation is not reported live: $(pe "$DRAIN/home" list)"
PATH="$DRAIN/bin:$PATH" FM_HOME="$DRAIN/home" FM_PROCEVENT_LAUNCH_CONFIRM_SECONDS=5 \
  "$ROOT/bin/fm-procevent-lavish.sh" arm "$drain_art" --for worker-drain \
  --agent-reply-file "$DRAIN/reply2" > "$DRAIN/arm2.out" 2> "$DRAIN/arm2.err" &
drain_arm=$!
sleep 1
kill -KILL "$drain_holder" 2>/dev/null || true
wait "$drain_holder" 2>/dev/null || true
wait "$drain_arm" \
  || fail "re-arm failed after the earlier claim was released: $(cat "$DRAIN/arm2.err")"
assert_contains "$(cat "$DRAIN/arm2.out")" "armed: $drain_id" \
  "re-arm did not launch the new generation once the earlier claim was released"
assert_not_contains "$(cat "$DRAIN/arm2.out")" "still-listening" \
  "re-arm reported the released earlier listener as still serving the board"
wait_for_lines "$DRAIN/replies" 2 \
  || fail "the new generation never handed the board the worker's reply"
[ "$(grep -c 'second drain reply' "$DRAIN/replies" 2>/dev/null || true)" = 1 ] \
  || fail "the new generation did not hand the board its own reply exactly once"
touch "$DRAIN/release2"
wait_for "$DRAIN/home/state/procevent-inbox/$drain_id.2.result" \
  || fail "the new generation never captured its round"
pass "re-arm launches the new generation once a draining earlier claim is released"

