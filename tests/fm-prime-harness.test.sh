#!/usr/bin/env bash
# Behavior tests for the verified Prime Agent crewmate adapter.
set -u

# shellcheck source=tests/fixtures.sh
. "$(dirname "${BASH_SOURCE[0]}")/fixtures.sh"

HARNESS="$ROOT/bin/fm-harness.sh"
SPAWN="$ROOT/bin/fm-spawn.sh"
TMP_ROOT=$(fm_test_tmproot fm-prime-harness)
trap 'rm -rf "$TMP_ROOT"' EXIT

MARKER_UNSETS=(-u CLAUDECODE -u PI_CODING_AGENT -u FM_PI_HARNESS -u GROK_AGENT
  -u CURSOR_AGENT -u CURSOR_INVOKED_AS
  -u PRIME_AGENT_KERNEL_OWNER_PID -u PRIME_AGENT_INTERNAL_DAEMON_WORKER)

# --- detection --------------------------------------------------------------

# detect_with [VAR=value...]: run fm-harness.sh with every harness identity
# marker cleared and only the given assignments set, so each case asserts
# exactly the markers it names.
detect_with() {
  env "${MARKER_UNSETS[@]}" "$@" "$HARNESS"
}

# Prime Agent sets PI_CODING_AGENT=true in its own process, so every Prime tool
# carries the Pi marker beside Prime's own. Either Prime marker must win alone.
test_prime_markers_outrank_the_inherited_pi_marker() {
  local out
  out=$(detect_with PI_CODING_AGENT=true PRIME_AGENT_KERNEL_OWNER_PID=4242)
  [ "$out" = prime ] || fail "the kernel-owner marker beside PI_CODING_AGENT read '$out', expected prime"
  out=$(detect_with PI_CODING_AGENT=true PRIME_AGENT_INTERNAL_DAEMON_WORKER=1)
  [ "$out" = prime ] || fail "the daemon-worker marker beside PI_CODING_AGENT read '$out', expected prime"
  out=$(detect_with PI_CODING_AGENT=true FM_PI_HARNESS=pi-signed PRIME_AGENT_KERNEL_OWNER_PID=4242)
  [ "$out" = prime ] || fail "a pi-signed launch marker beside a Prime marker read '$out', expected prime"
  pass "either Prime marker outranks the Pi marker Prime sets for its own tools"
}

test_pi_detection_is_unchanged() {
  local out
  out=$(detect_with PI_CODING_AGENT=true)
  [ "$out" = pi ] || fail "PI_CODING_AGENT alone read '$out', expected pi"
  out=$(detect_with PI_CODING_AGENT=true FM_PI_HARNESS=pi-signed)
  [ "$out" = pi-signed ] || fail "the signed Pi launch boundary read '$out', expected pi-signed"
  out=$(detect_with PI_CODING_AGENT=true PRIME_AGENT_KERNEL_OWNER_PID= PRIME_AGENT_INTERNAL_DAEMON_WORKER=)
  [ "$out" = pi ] || fail "empty Prime markers beside PI_CODING_AGENT read '$out', expected pi"
  pass "pi and pi-signed detection is unchanged when no Prime marker is set"
}

# Claude and Cursor keep their place ahead of Prime: fm-spawn clears CLAUDECODE
# and the Cursor markers at the Prime launch boundary, while a session started
# from inside a Prime tool sets its own marker fresh.
test_claude_and_cursor_markers_keep_precedence() {
  local out
  out=$(detect_with CLAUDECODE=1 PI_CODING_AGENT=true PRIME_AGENT_KERNEL_OWNER_PID=4242)
  [ "$out" = claude ] || fail "CLAUDECODE beside Prime markers read '$out', expected claude"
  out=$(detect_with CURSOR_AGENT=1 PRIME_AGENT_KERNEL_OWNER_PID=4242)
  [ "$out" = cursor ] || fail "CURSOR_AGENT beside a Prime marker read '$out', expected cursor"
  pass "claude and cursor markers keep precedence over Prime markers"
}

# Prime tools descend from the session worker, whose process title is
# prime-agent. The probe runs in a command substitution so the renamed process
# stays in the parent chain, as a real worker does for its kernel.
test_detects_only_an_exact_prime_agent_ancestor() {
  local dir bin out
  dir="$TMP_ROOT/detect"
  mkdir -p "$dir"
  cp "$(command -v bash)" "$dir/prime-agent"
  out=$(env "${MARKER_UNSETS[@]}" "$dir/prime-agent" -c "r=\$(\"$HARNESS\"); printf '%s' \"\$r\"")
  [ "$out" = prime ] || fail "fm-harness.sh under a prime-agent process reported '$out', expected prime"
  for bin in prime prime-agentx primeagent; do
    cp "$(command -v bash)" "$dir/$bin"
    out=$(env "${MARKER_UNSETS[@]}" "$dir/$bin" -c "r=\$(\"$HARNESS\"); printf '%s' \"\$r\"")
    [ "$out" != prime ] || fail "fm-harness.sh misdetected unrelated process '$bin' as prime"
  done
  pass "prime is detected through an exact prime-agent ancestor only"
}

# --- spawn scaffolding ------------------------------------------------------

# Prime spawns run on the herdr backend, the only one verified for Prime. The
# tmux fake records every call so a refused tmux spawn can prove it created no
# endpoint.
make_prime_fakebin() {
  local dir=$1 fakebin
  fakebin=$(fm_fakebin "$dir")
  fm_test_fake_herdr_spawn "$fakebin"
  cat > "$fakebin/tmux" <<'SH'
#!/usr/bin/env bash
set -u
printf '%s\n' "$*" >> "${FM_FAKE_TMUX_LOG:-/dev/null}"
case "$*" in
  *"#{pane_current_path}"*) printf '%s\n' "${FM_FAKE_PANE_PATH:-}"; exit 0 ;;
esac
case "${1:-}" in
  display-message) printf 'firstmate\n' ;;
esac
exit 0
SH
  chmod +x "$fakebin/tmux"
  # Like the real Prime Agent, the fake sets PI_CODING_AGENT=true and the
  # kernel-owner marker for its tool, then runs the probe with whatever else the
  # launch command left in the environment.
  cat > "$fakebin/prime-agent" <<'SH'
#!/usr/bin/env bash
set -u
[ -n "${FM_FAKE_HARNESS_RESULT:-}" ] || exit 0
PI_CODING_AGENT=true PRIME_AGENT_KERNEL_OWNER_PID=$$ "$FM_FAKE_HARNESS_PROBE" > "$FM_FAKE_HARNESS_RESULT"
SH
  chmod +x "$fakebin/prime-agent"
  fm_fake_exit0 "$fakebin" treehouse gh-axi gh
  printf '%s\n' "$fakebin"
}

make_spawn_case() {  # <name>
  local name=$1 case_dir home proj wt fakebin id
  case_dir="$TMP_ROOT/$name"
  home="$case_dir/home"
  proj="$case_dir/project"
  wt="$case_dir/wt"
  fakebin=$(make_prime_fakebin "$case_dir/fake")
  id="prime-$name-x1"
  mkdir -p "$home/data/$id" "$home/projects" "$home/state" "$home/config"
  cat > "$home/data/$id/brief.md" <<'EOF'
# Task
## Captain's intent
Exercise Prime dispatch.

## Firstmate spec
Verify the Prime harness behavior under test.
EOF
  fm_git_worktree "$proj" "$wt" "fm/$id"
  touch "$home/state/.last-watcher-beat"
  printf '%s\n' "$case_dir|$home|$proj|$wt|$fakebin|$id"
}

run_prime_spawn() {  # <home> <proj> <wt> <fakebin> <id> [extra args...]
  local home=$1 proj=$2 wt=$3 fakebin=$4 id=$5
  shift 5
  FM_FAKE_LAUNCH_LOG="$home/launch.log" \
    FM_FAKE_HARNESS_PROBE="$HARNESS" \
    FM_FAKE_EXECUTE_LAUNCH_MATCH="${FM_FAKE_EXECUTE_LAUNCH_MATCH:-}" \
    FM_FAKE_HARNESS_RESULT="${FM_FAKE_HARNESS_RESULT:-}" \
    PATH="${FM_TEST_PRIME_PATH:-$PATH}" \
    fm_test_run_spawn_herdr "$home" "$wt" "$fakebin" "$id" "$proj" prime "$@"
}

# path_without_prime <fakebin>: the fakebin plus every PATH entry that holds no
# prime-agent, so a missing-executable case cannot find a host install.
path_without_prime() {
  local out=$1 dir
  local -a dirs
  IFS=: read -r -a dirs <<< "$PATH"
  for dir in "${dirs[@]}"; do
    [ -n "$dir" ] || continue
    [ -e "$dir/prime-agent" ] && continue
    out="$out:$dir"
  done
  printf '%s' "$out"
}

# --- spawn ------------------------------------------------------------------

test_spawn_launch_shape() {
  local rec case_dir home proj wt fakebin id out status launch
  rec=$(make_spawn_case launch)
  IFS='|' read -r case_dir home proj wt fakebin id <<EOF
$rec
EOF
  out=$(run_prime_spawn "$home" "$proj" "$wt" "$fakebin" "$id" --mode no-mistakes --yolo off)
  status=$?
  expect_code 0 "$status" "prime spawn should succeed: $out"
  assert_contains "$out" "spawned $id harness=prime" "prime spawn did not report success"

  launch=$(cat "$home/launch.log")
  assert_contains "$launch" "'$fakebin/prime-agent' " "prime launch did not pin the resolved executable"
  # Skill discovery reads every global and ancestor skill directory into the
  # startup prompt, which once overflowed a 262k-token context window.
  assert_contains "$launch" ' --no-skills ' "prime launch omitted --no-skills"
  # A resident session outlives /quit and a closed pane with its worker and
  # kernel still running; a client-owned one ends with the pane.
  assert_contains "$launch" ' --no-session ' "prime launch omitted --no-session"
  assert_contains "$launch" "-e '$home/state/$id.prime-ext.ts' " "prime launch did not load the per-task extension"
  assert_contains "$launch" 'encode launch-brief' "prime launch did not deliver the brief positionally"
  assert_not_contains "$launch" '--thinking' "prime launch invented an effort when none was chosen"
  assert_grep 'harness=prime' "$home/state/$id.meta" "prime harness was not recorded in meta"
  assert_grep 'backend=herdr' "$home/state/$id.meta" "prime spawn was not recorded on the herdr backend"
  assert_present "$home/state/$id.prime-ext.ts" "prime spawn did not write the per-task extension"
  assert_present "$home/state/$id.busy-gen" "prime spawn did not arm the busy-state contract"
  pass "prime spawn on herdr launches without skills or a resident session and loads its extension"
}

# Only Herdr detects a Prime pane natively. On any other backend the control
# plane reads a running Prime pane as ambiguous and refuses interrupt and exit,
# so the spawn must refuse before it creates an endpoint.
test_spawn_refuses_non_herdr_backend() {
  local rec case_dir home proj wt fakebin id out status
  rec=$(make_spawn_case tmux-refused)
  IFS='|' read -r case_dir home proj wt fakebin id <<EOF
$rec
EOF
  out=$(env -u HERDR_ENV -u HERDR_PANE_ID FM_FAKE_TMUX_LOG="$home/tmux.log" \
    FM_FAKE_LAUNCH_LOG="$home/launch.log" \
    bash -c '. "$1/tests/fixtures.sh"; shift; fm_test_run_spawn "$@"' _ "$ROOT" \
    "$home" "$wt" "$fakebin" "$id" "$proj" prime --mode no-mistakes --yolo off)
  status=$?
  [ "$status" -ne 0 ] || fail "prime spawn succeeded on the default tmux backend: $out"
  assert_contains "$out" "prime is verified on the herdr backend only; backend 'tmux' is unverified for Prime" \
    "prime tmux refusal did not name the unverified backend"
  if [ -f "$home/tmux.log" ]; then
    assert_no_grep 'new-window\|new-session\|send-keys' "$home/tmux.log" "a refused prime spawn still touched a tmux endpoint"
  fi
  assert_absent "$home/launch.log" "a refused prime spawn still sent a launch"
  assert_absent "$home/state/$id.meta" "a refused prime spawn still recorded a task"
  assert_absent "$home/state/$id.prime-ext.ts" "a refused prime spawn still wrote its extension"
  assert_absent "$home/state/$id.busy-gen" "a refused prime spawn still armed the busy-state contract"
  pass "prime spawn refuses a non-herdr backend before creating an endpoint"
}

test_spawn_launch_clears_inherited_foreign_markers() {
  local rec case_dir home proj wt fakebin id result out status
  rec=$(make_spawn_case inherited-markers)
  IFS='|' read -r case_dir home proj wt fakebin id <<EOF
$rec
EOF
  result="$case_dir/harness-result"
  out=$(CLAUDECODE=1 GROK_AGENT=1 FM_PI_HARNESS=pi-signed \
    CURSOR_AGENT=1 CURSOR_INVOKED_AS=cursor-agent \
    FM_FAKE_EXECUTE_LAUNCH_MATCH="$fakebin/prime-agent" FM_FAKE_HARNESS_RESULT="$result" \
    run_prime_spawn "$home" "$proj" "$wt" "$fakebin" "$id" --mode no-mistakes --yolo off)
  status=$?
  expect_code 0 "$status" "prime spawn from a marked backend should succeed: $out"
  [ -f "$result" ] || fail "the generated prime launch never executed its harness probe"
  [ "$(cat "$result")" = prime ] \
    || fail "a Prime tool inherited a foreign harness identity: $(cat "$result")"
  pass "prime launch clears foreign markers so a Prime tool detects prime"
}

test_spawn_maps_effort_and_model() {
  local rec case_dir home proj wt fakebin id launch effort
  for effort in low medium high xhigh max; do
    rec=$(make_spawn_case "effort-$effort")
    IFS='|' read -r case_dir home proj wt fakebin id <<EOF
$rec
EOF
    run_prime_spawn "$home" "$proj" "$wt" "$fakebin" "$id" --mode no-mistakes --yolo off \
      --model openrouter/moonshotai/kimi-k2.6 --effort "$effort" >/dev/null \
      || fail "prime spawn with effort $effort failed"
    launch=$(cat "$home/launch.log")
    assert_contains "$launch" "--thinking '$effort'" "prime effort $effort did not map to --thinking"
    assert_contains "$launch" "--model 'openrouter/moonshotai/kimi-k2.6'" "prime spawn dropped the model axis"
  done
  pass "prime maps the shared effort vocabulary to --thinking and keeps the provider-qualified model"
}

test_spawn_refuses_without_prime_binary() {
  local rec case_dir home proj wt fakebin id out status
  rec=$(make_spawn_case no-binary)
  IFS='|' read -r case_dir home proj wt fakebin id <<EOF
$rec
EOF
  rm -f "$fakebin/prime-agent"
  out=$(FM_TEST_PRIME_PATH="$(path_without_prime "$fakebin")" \
    run_prime_spawn "$home" "$proj" "$wt" "$fakebin" "$id" --mode no-mistakes --yolo off)
  status=$?
  [ "$status" -ne 0 ] || fail "prime spawn succeeded with no prime-agent executable"
  assert_contains "$out" "prime-agent executable not found on PATH" "prime spawn did not name the missing executable"
  assert_absent "$home/launch.log" "a refused prime spawn still created an endpoint"
  pass "prime spawn refuses before creating an endpoint when prime-agent is absent"
}

# No Prime primary integration exists, so a secondmate on Prime could never arm
# its supervision cycle.
test_spawn_refuses_secondmate() {
  local case_dir home fakebin id out status
  case_dir="$TMP_ROOT/secondmate"
  home="$case_dir/home"
  fakebin=$(make_prime_fakebin "$case_dir/fake")
  id="prime-secondmate-x1"
  mkdir -p "$home/data/$id" "$home/projects" "$home/state" "$home/config" "$case_dir/prime"
  printf 'charter\n' > "$home/data/$id/brief.md"
  out=$(cd "$case_dir" && FM_ROOT_OVERRIDE='' FM_HOME="$home" \
    FM_STATE_OVERRIDE="$home/state" FM_DATA_OVERRIDE="$home/data" \
    FM_PROJECTS_OVERRIDE="$home/projects" FM_CONFIG_OVERRIDE="$home/config" \
    FM_SPAWN_NO_GUARD=1 TMUX="fake,1,0" \
    PATH="$fakebin:$PATH" \
    "$SPAWN" "$id" prime --secondmate 2>&1)
  status=$?
  [ "$status" -ne 0 ] || fail "prime was accepted as a secondmate harness"
  assert_contains "$out" "prime is a verified crewmate/scout adapter only" \
    "prime secondmate refusal did not explain the boundary"
  pass "prime is refused as a secondmate harness"
}

test_prime_markers_outrank_the_inherited_pi_marker
test_pi_detection_is_unchanged
test_claude_and_cursor_markers_keep_precedence
test_detects_only_an_exact_prime_agent_ancestor
test_spawn_launch_shape
test_spawn_refuses_non_herdr_backend
test_spawn_launch_clears_inherited_foreign_markers
test_spawn_maps_effort_and_model
test_spawn_refuses_without_prime_binary
test_spawn_refuses_secondmate
