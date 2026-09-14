#!/usr/bin/env bash
# tests/fm-prime-herdr-live-e2e.test.sh - opt-in live guard for the Prime Agent
# crewmate adapter on a real, isolated Herdr lab session.
#
# The adapter rests on vendor-controlled facts: the environment markers Prime's
# tools inherit, its extension lifecycle events, Herdr's native detection of the
# pane, its single Ctrl+C interrupt, and the client-owned worker that
# --no-session ties to the pane. A stub can only restate those assumptions, so
# this guard launches the real prime-agent with the exact launch command
# bin/fm-spawn.sh composes and the extension it writes. It spends two short
# model turns.
#
# Standard CI has no prime-agent, provider credentials, or Herdr, so the guard is
# opt-in and on-demand:
#   FM_PRIME_HERDR_LIVE=1 HERDR_LAB_HELPER=bin/fm-herdr-lab.sh \
#     [FM_PRIME_LIVE_MODEL=openrouter/moonshotai/kimi-k2.6] \
#     tests/fm-prime-herdr-live-e2e.test.sh
# Run it after every Prime Agent or Herdr upgrade before trusting
# docs/verification/prime.md.
set -u

if [ "${FM_PRIME_HERDR_LIVE:-0}" != 1 ]; then
  echo "skip: set FM_PRIME_HERDR_LIVE=1 to run the live Prime Agent Herdr guard"
  exit 0
fi

# shellcheck source=tests/fixtures.sh
. "$(dirname "${BASH_SOURCE[0]}")/fixtures.sh"
# shellcheck source=/dev/null
. "$ROOT/bin/fm-busy-lib.sh"

note() { printf '# %s\n' "$1"; }

for tool in herdr jq; do
  command -v "$tool" >/dev/null 2>&1 || fail "$tool is required for the live Prime Agent guard"
done
PRIME_BIN=$(command -v prime-agent 2>/dev/null) \
  || fail "prime harness is not installed: prime-agent was not found on PATH, so nothing was verified"
# prime-agent prints its version on stderr.
note "prime-agent $("$PRIME_BIN" --version 2>&1 | head -1) at $PRIME_BIN"
note "$(herdr --version 2>/dev/null | head -1)"
MODEL=${FM_PRIME_LIVE_MODEL:-openrouter/moonshotai/kimi-k2.6}
note "model $MODEL"

LAB_HELPER=${HERDR_LAB_HELPER:-$ROOT/bin/fm-herdr-lab.sh}
SESSION=$("$LAB_HELPER" name prime-live) || fail "could not name an isolated Herdr lab session"
TMP_ROOT=$(fm_test_tmproot fm-prime-herdr-live)
PANE=
PROVISIONED=0

cleanup() {
  local rc=$?
  trap - EXIT
  if [ "$PROVISIONED" = 1 ] && ! "$LAB_HELPER" teardown "$SESSION"; then
    rc=1
  fi
  rm -rf "$TMP_ROOT"
  exit "$rc"
}
trap cleanup EXIT

lab() { "$LAB_HELPER" run "$SESSION" "$@"; }

wait_for() {  # <seconds> <description> <command...>
  local deadline=$((SECONDS + $1)) description=$2
  shift 2
  while [ "$SECONDS" -lt "$deadline" ]; do
    "$@" && return 0
    sleep 1
  done
  fail "timed out waiting for $description"
}

HOME_DIR="$TMP_ROOT/home"
PROJ="$TMP_ROOT/project"
WT="$TMP_ROOT/wt"
ID=prime-live-x1
STATE="$HOME_DIR/state"
PROBE="$TMP_ROOT/probe.txt"
mkdir -p "$HOME_DIR/data/$ID" "$HOME_DIR/projects" "$STATE" "$HOME_DIR/config"
touch "$STATE/.last-watcher-beat"
fm_git_worktree "$PROJ" "$WT" "fm/$ID"
cat > "$HOME_DIR/data/$ID/brief.md" <<EOF
# Task
## Captain's intent
Live Prime Agent adapter probe.

## Firstmate spec
Use the ipython tool to run exactly this Python, then reply with DONE only:
import os, subprocess
r = subprocess.run(["$ROOT/bin/fm-harness.sh"], capture_output=True, text=True)
open("$PROBE", "w").write(" ".join([r.stdout.strip(), os.environ.get("PI_CODING_AGENT", "unset"), str(os.getpid()), str(os.getppid())]) + "\n")
EOF

# Compose the launch with the real fm-spawn against a recording herdr fake, on
# the herdr backend Prime is verified for. The spawn resolves the real
# prime-agent and writes the real extension; only the endpoint creation is
# faked, and the recorded command then runs in the lab pane.
FAKEBIN=$(fm_fakebin "$TMP_ROOT/fake")
fm_test_fake_herdr_spawn "$FAKEBIN"
fm_fake_exit0 "$FAKEBIN" treehouse gh-axi gh
out=$(FM_FAKE_LAUNCH_LOG="$TMP_ROOT/launch.log" \
  fm_test_run_spawn_herdr "$HOME_DIR" "$WT" "$FAKEBIN" "$ID" "$PROJ" prime --model "$MODEL" --effort low \
  --mode no-mistakes --yolo off) || fail "fm-spawn could not compose the prime launch: $out"
LAUNCH=$(grep -F -- "$PRIME_BIN" "$TMP_ROOT/launch.log" | head -1)
[ -n "$LAUNCH" ] || fail "fm-spawn recorded no launch command naming $PRIME_BIN"
[ -f "$STATE/$ID.prime-ext.ts" ] || fail "fm-spawn did not write the prime extension"

"$LAB_HELPER" provision "$SESSION" || fail "could not provision the isolated Herdr lab session"
PROVISIONED=1
PANE=$(lab workspace create --cwd "$WT" --label prime-live --no-focus | jq -r '.result.root_pane.pane_id // empty')
[ -n "$PANE" ] || fail "could not create the lab pane"
lab pane run "$PANE" "$LAUNCH" >/dev/null || fail "could not run the prime launch in the lab pane"

native_agent() {
  lab agent get "$PANE" 2>/dev/null | jq -r '.result.agent.agent // empty' 2>/dev/null
}
native_is_prime() { [ "$(native_agent)" = prime-agent ]; }
native_is_gone() { [ -z "$(native_agent)" ]; }
busy_is() { [ "$(fm_busy_classify tmux fake:w prime "$ID" "$STATE")" = "$1" ]; }
probe_written() { [ -s "$PROBE" ]; }

wait_for 60 "Herdr to detect the Prime pane" native_is_prime
pass "real herdr: detects the Prime pane natively as agent prime-agent"

wait_for 240 "the launch turn's probe" probe_written
read -r detected pi_marker kernel_pid worker_pid < "$PROBE"
[ "$pi_marker" = true ] || fail "Prime tools no longer inherit PI_CODING_AGENT=true (got '$pi_marker'), so the precedence case is vacuous; recheck the marker"
[ "$detected" = prime ] || fail "a real Prime tool detected harness '$detected' instead of prime"
pass "real prime-agent: a tool beside PI_CODING_AGENT=true detects harness prime"

wait_for 120 "the extension to settle the launch turn idle" busy_is "idle prime-ext"
[ -f "$STATE/$ID.turn-ended" ] || fail "turn_end did not touch the turn-ended notification marker"
pass "real prime-agent: the generated extension settles the turn idle and touches the turn-end marker"

lab pane send-text "$PANE" 'Use the ipython tool to run import time; time.sleep(90); print(1). Wait for it to finish, then reply with DONE only.' >/dev/null
lab pane send-keys "$PANE" enter >/dev/null
wait_for 60 "the long turn to start" busy_is "busy prime-ext"
sleep 8
busy_is "busy prime-ext" || fail "the long turn ended before the interrupt, so the interrupt case would be vacuous"
lab pane send-keys "$PANE" ctrl+c >/dev/null
sleep 3
native_is_prime || fail "one Ctrl+C stopped the Prime agent instead of cancelling its run"
wait_for 60 "the interrupted run to settle idle" busy_is "idle prime-ext"
pass "real prime-agent: one Ctrl+C cancels the run, keeps the agent, and settles idle"

sleep 5
lab pane send-text "$PANE" '/quit' >/dev/null
lab pane send-keys "$PANE" enter >/dev/null
wait_for 30 "Herdr to report the Prime agent gone after /quit" native_is_gone
workers_gone() { ! kill -0 "$kernel_pid" 2>/dev/null && ! kill -0 "$worker_pid" 2>/dev/null; }
wait_for 60 "the client-owned worker and kernel to end" workers_gone
pass "real prime-agent: /quit ends the client-owned worker and its Python kernel"
