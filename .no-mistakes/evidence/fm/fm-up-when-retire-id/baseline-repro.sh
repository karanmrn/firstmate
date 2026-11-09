#!/usr/bin/env bash
set -euo pipefail
ROOT=$PWD
unset FM_ROOT_OVERRIDE FM_STATE_OVERRIDE FM_DATA_OVERRIDE FM_CONFIG_OVERRIDE FM_PROJECTS_OVERRIDE FM_GATE_REFUSE_BYPASS
WORK=$(mktemp -d "$ROOT/.when-baseline.XXXXXX")
BASE_SCRIPT="$ROOT/bin/.fm-procevent-when-baseline-$$.sh"
export FM_HOME="$WORK/home" FM_PROCEVENT_CLAIM_ROOT="$WORK/claims"
mkdir -p "$WORK/tmp"
export TMPDIR="$WORK/tmp"
trap 'rm -f "$BASE_SCRIPT"; rm -rf "$WORK"' EXIT
git show bc9370e8868421ce6791d33455301b4287a4cef3:bin/fm-procevent-when.sh > "$BASE_SCRIPT"
chmod +x "$BASE_SCRIPT"
"$ROOT/bin/fm-lab-home.sh" create "$FM_HOME"
printf 'BEFORE FIX: executable adapter from base bc9370e8868421ce6791d33455301b4287a4cef3\n'
"$BASE_SCRIPT" arm listed --condition false --action true
"$BASE_SCRIPT" arm when-listed --condition false --action true
listing=$("$ROOT/bin/fm-procevent.sh" list)
printf '%s\n' "$listing"
listed=$(printf '%s\n' "$listing" | awk '$1 == "when-listed" && $2 == "when" {print $1}')
test "$listed" = when-listed
printf 'Retiring ID copied from list: %s\n' "$listed"
"$BASE_SCRIPT" retire "$listed"
"$ROOT/bin/fm-procevent.sh" list
test -f "$FM_HOME/state/procevent/when-listed.source"
test -f "$FM_HOME/state/when/when-listed.spec"
test ! -e "$FM_HOME/state/procevent/when-when-listed.source"
printf 'REPRODUCED: requested when-listed remains registered, but sibling when-when-listed was removed.\n'
"$ROOT/bin/fm-procevent.sh" sweep-home
