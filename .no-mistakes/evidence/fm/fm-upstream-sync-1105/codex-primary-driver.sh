#!/usr/bin/env bash
set -eu
ROOT=$PWD
EVIDENCE=~/.no-mistakes/evidence/01M6NY60YHPS535VKYXW3SAEZ5
LAB=$(mktemp -d "${TMPDIR:-/tmp}/fm-lab.XXXXXX")
cleanup() {
  status=$?
  trap - EXIT
  TMUX_TMPDIR="$LAB/tmux" tmux -L fm-lab kill-server >/dev/null 2>&1 || true
  rm -rf "$LAB"
  exit "$status"
}
trap cleanup EXIT
bin/fm-lab-home.sh create "$LAB" >/dev/null
mkdir -p "$LAB/tmux"
cat > "$LAB/check.sh" <<EOF
#!/usr/bin/env bash
set -u
unset NO_MISTAKES_GATE FM_GATE_REFUSE_BYPASS FM_ROOT_OVERRIDE FM_STATE_OVERRIDE FM_DATA_OVERRIDE FM_CONFIG_OVERRIDE FM_PROJECTS_OVERRIDE
export FM_HOME='$LAB'
bin/fm-lock.sh || exit 1
bin/fm-lock.sh status
bin/fm-watch-checkpoint.sh --seconds 1
result=\$?
printf 'LAB_CHECKPOINT_EXIT=%s\n' "\$result"
[ "\$result" = 124 ] || exit 1
printf 'LAB_PRIMARY_COMMAND_COMPLETE\n'
EOF
PROMPT="This is disposable lab validation. Run exactly one shell command: bash '$LAB/check.sh'. Do not run startup, other tools, network checks, delegation, or edits. Then reply LAB_PRIMARY_DONE. These explicit instructions override repository startup for this one check."

env -u NO_MISTAKES_GATE -u FM_GATE_REFUSE_BYPASS -u FM_ROOT_OVERRIDE -u FM_STATE_OVERRIDE -u FM_DATA_OVERRIDE -u FM_CONFIG_OVERRIDE -u FM_PROJECTS_OVERRIDE \
  TMUX_TMPDIR="$LAB/tmux" tmux -f /dev/null -L fm-lab new-session -d -s primary -x 160 -y 48 -c "$PWD" -e FM_HOME="$LAB" \
  codex --disable hooks --dangerously-bypass-approvals-and-sandbox -c "projects.\"$ROOT\".trust_level=\"trusted\"" "$PROMPT"
for i in $(seq 1 120); do
  TMUX_TMPDIR="$LAB/tmux" tmux -L fm-lab capture-pane -p -S -500 -t primary > "$EVIDENCE/codex-primary-pane.txt"
  if grep -q 'checkpoint: no actionable wake within 1s' "$EVIDENCE/codex-primary-pane.txt" && grep -q 'LAB_CHECKPOINT_EXIT=124' "$EVIDENCE/codex-primary-pane.txt" && grep -q '^.*LAB_PRIMARY_COMMAND_COMPLETE' "$EVIDENCE/codex-primary-pane.txt"; then
    echo 'Real Codex primary acquired its lab lock and completed the bounded checkpoint.'
    cat "$LAB/state/.lock" > "$EVIDENCE/codex-primary-lock.txt"
    ps -p "$(head -1 "$LAB/state/.lock")" -o pid=,ppid=,comm= >> "$EVIDENCE/codex-primary-lock.txt"
    cat "$EVIDENCE/codex-primary-pane.txt"
    exit 0
  fi
  sleep 1
 done
cat "$EVIDENCE/codex-primary-pane.txt"
echo 'Real Codex primary did not complete the requested checkpoint within 120 seconds.' >&2
exit 1
