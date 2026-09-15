#!/usr/bin/env bash
# Drive herdr-workspace-move.py (base vs fixed) against a real Herdr lab session
# through a >104-byte socket path (macOS sun_path limit).
set -u
ROOT=$1; BASE=$2
LAB="$ROOT/bin/fm-herdr-lab.sh"
S=$("$LAB" name moverlong)
T=$(mktemp -d "$(cd "${TMPDIR:-/tmp}" && pwd -P)/fm-mover-long.XXXXXX")
trap '"$LAB" teardown "$S"; echo "teardown exit=$?"; rm -rf "$T"' EXIT
"$LAB" provision "$S" >/dev/null || { echo "provision failed"; exit 1; }
lab() { "$LAB" run "$S" "$@"; }
SOCK=$(herdr session list --json | jq -r --arg n "$S" '.sessions[] | select(.name==$n) | .socket_path')
echo "lab session: $S"
echo "real socket: $SOCK (${#SOCK} bytes)"
W1=$(lab workspace create --cwd "$ROOT" --label mv-one --no-focus | jq -r '.result.workspace.workspace_id')
W2=$(lab workspace create --cwd "$ROOT" --label mv-two --no-focus | jq -r '.result.workspace.workspace_id')
order() { lab workspace list | jq -r '[.result.workspaces[] | .label // .workspace_id] | join(",")'; }
echo "workspaces: $W1 $W2; order before: $(order)"
LONGDIR="$T/$(printf 'd%.0s' $(seq 1 110))"
mkdir -p "$LONGDIR"
ln -s "$(dirname "$SOCK")" "$LONGDIR/s"
LONG="$LONGDIR/s/herdr.sock"
echo "long socket path: ${#LONG} bytes"
git -C "$ROOT" show "$BASE:bin/backends/herdr-workspace-move.py" > "$T/base-mover.py"
N=$(lab workspace list | jq '.result.workspaces | length')
echo "--- base mover (pre-fix), long path, move $W2 to index 0"
python3 "$T/base-mover.py" "$LONG" "$W2" 0; echo "exit=$?"; echo "order: $(order)"
echo "--- fixed mover, long path, move $W2 to index 0"
python3 "$ROOT/bin/backends/herdr-workspace-move.py" "$LONG" "$W2" 0 | jq -c '{type:.result.type, ids:[.result.workspaces[].workspace_id]}'; echo "exit=${PIPESTATUS[0]}"; echo "order: $(order)"
echo "--- fixed mover, short real path, move $W2 back to index $((N-1))"
python3 "$ROOT/bin/backends/herdr-workspace-move.py" "$SOCK" "$W2" "$((N-1))" >/dev/null; echo "exit=$?"; echo "order: $(order)"
echo "--- adversarial: long path whose directory does not exist"
python3 "$ROOT/bin/backends/herdr-workspace-move.py" "$LONGDIR/missing/herdr.sock" "$W2" 0; echo "exit=$?"
echo "--- adversarial: long path to directory with no socket"
python3 "$ROOT/bin/backends/herdr-workspace-move.py" "$LONGDIR/nosock.sock" "$W2" 0; echo "exit=$?"
echo "--- adversarial: relative socket path"
python3 "$ROOT/bin/backends/herdr-workspace-move.py" "herdr.sock" "$W2" 0; echo "exit=$?"
echo "--- adversarial: unknown workspace id over long path"
python3 "$ROOT/bin/backends/herdr-workspace-move.py" "$LONG" "w-does-not-exist" 0; echo "exit=$?"
