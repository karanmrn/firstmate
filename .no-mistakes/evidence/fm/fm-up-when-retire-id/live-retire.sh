#!/usr/bin/env bash
set -euo pipefail
ROOT=$PWD
unset FM_ROOT_OVERRIDE FM_STATE_OVERRIDE FM_DATA_OVERRIDE FM_CONFIG_OVERRIDE FM_PROJECTS_OVERRIDE FM_GATE_REFUSE_BYPASS
WORK=$(mktemp -d "$ROOT/.when-live.XXXXXX")
mkdir -p "$WORK/tmp"
export TMPDIR="$WORK/tmp" FM_PROCEVENT_CLAIM_ROOT="$WORK/claims"
export FM_HOME="$WORK/home"
cleanup() {
  rc=$?
  trap - EXIT
  if ! "$ROOT/bin/fm-procevent.sh" sweep-home; then
    printf 'ERROR: disposable runner cleanup failed\n'
    exit 1
  fi
  rm -rf "$WORK"
  printf 'Disposable home and runners removed.\n'
  exit "$rc"
}
trap cleanup EXIT
"$ROOT/bin/fm-lab-home.sh" create "$FM_HOME"
when_cli() { "$ROOT/bin/fm-procevent-when.sh" "$@"; }
pe() { "$ROOT/bin/fm-procevent.sh" "$@"; }
state_check() {
  sid=$1 expected=$2
  for file in "$FM_HOME/state/when/$sid.spec" "$FM_HOME/state/when/$sid.trust" "$FM_HOME/state/procevent/$sid.source"; do
    if [ "$expected" = present ]; then test -f "$file"; else test ! -e "$file"; fi
  done
  printf 'Persisted registration, spec, trust for %s: %s\n' "$sid" "$expected"
}
wait_result() {
  for ((n=0; n<200; n++)); do
    test ! -e "$FM_HOME/state/procevent/$1.source" && test -f "$FM_HOME/state/procevent-inbox/$1.1.result" && return 0
    sleep 0.1
  done
  printf 'ERROR: no completed result for %s\n' "$1"
  return 1
}
printf 'TARGET HEAD: '
git rev-parse HEAD
printf '\nSCENARIO: listed ID and overlapping live sibling\n'
for name in listed when-listed; do
  when_cli arm "$name" --interval 0.1 --stable 1 --condition /bin/bash -c 'test -e "$1"' _ "$WORK/$name.trigger" --action /bin/bash -c 'printf "invoked\n" >> "$1"; printf "action completed\n"' _ "$WORK/$name.action"
done
pe reconcile
listing=$(pe list)
printf '%s\n' "$listing"
listed=$(printf '%s\n' "$listing" | awk '$1 == "when-listed" && $2 == "when" && $3 == "live" {print $1}')
sibling=$(printf '%s\n' "$listing" | awk '$1 == "when-when-listed" && $2 == "when" && $3 == "live" {print $1}')
test "$listed" = when-listed
test "$sibling" = when-when-listed
for attempt in 1 2; do
  printf 'Retire exact listed ID, attempt %s:\n' "$attempt"
  when_cli retire "$listed"
  state_check when-listed absent
  state_check when-when-listed present
  pe list
done
touch "$WORK/listed.trigger" "$WORK/when-listed.trigger"
wait_result when-when-listed
test ! -e "$WORK/listed.action"
test "$(cat "$WORK/when-listed.action")" = invoked
printf 'Retired action did not run. Preserved sibling action ran once.\n'
result="$FM_HOME/state/procevent-inbox/when-when-listed.1.result"
printf '\nSCENARIO: terminal outcome acknowledgement and exact-ID cleanup\n'
cat "$result"
test "$(when_cli classify "$result")" = fired
pe handled when-when-listed 1
handled="$FM_HOME/state/procevent-inbox/when-when-listed.1.handled"
test -f "$handled"
cp "$result" "$WORK/result.before"
cp "$handled" "$WORK/handled.before"
test -e "$FM_HOME/state/when/when-when-listed.fired"
when_cli retire "$sibling"
when_cli retire "$sibling"
state_check when-when-listed absent
test ! -e "$FM_HOME/state/when/when-when-listed.fired"
cmp "$result" "$WORK/result.before"
cmp "$handled" "$WORK/handled.before"
pe handled when-when-listed 1
printf 'Captured result and handled acknowledgement remain byte-identical.\n'
when_cli arm when-listed --stable 1 --condition true --action true
when_cli retire when-when-listed
printf 'The same prefixed name can be armed again after cleanup.\n'
printf '\nSCENARIO: bare names, maximum listed ID, and absent retries\n'
when_cli arm bare --condition false --action true
when_cli retire bare
when_cli retire bare
state_check when-bare absent
when_cli retire when-missing
long_name=$(printf '%059d' 1)
when_cli arm "$long_name" --condition false --action true
when_cli retire "$(when_cli source-id "$long_name")"
when_cli retire "when-$long_name"
state_check "when-$long_name" absent
printf '\nSCENARIO: unsafe and overlong IDs cannot retire a valid sibling\n'
when_cli arm guard --condition false --action true
for invalid in 'when-' 'when-../guard' 'when-/guard' "when-${long_name}0"; do
  printf 'Retire invalid ID: %s\n' "$invalid"
  if when_cli retire "$invalid"; then
    printf 'ERROR: invalid ID accepted\n'
    exit 1
  fi
  state_check when-guard present
done
when_cli retire when-guard
pe list
printf 'All live retirement scenarios passed.\n'
