#!/usr/bin/env bash
set -euo pipefail
ROOT=$PWD
AREA=$(mktemp -d "$ROOT/.test-phase-tmp/herdr.XXXXXX")
mkdir -p "$AREA/shim"
export FM_HERDR_LAB_STATE_DIR="$AREA/ownership"
HELPER="$ROOT/bin/fm-herdr-lab.sh"
SESSION=$("$HELPER" name sync-proof)
ORIGINAL_PATH=$PATH
export HELPER SESSION ORIGINAL_PATH
cleanup() { PATH="$ORIGINAL_PATH" "$HELPER" teardown "$SESSION"; }
trap cleanup EXIT
"$HELPER" provision "$SESSION"
"$HELPER" run "$SESSION" status --json
bin/fm-lab-home.sh create "$AREA/home"
export FM_HOME="$AREA/home" HERDR_SESSION="$SESSION" SHELL=/bin/bash
unset HERDR_ENV HERDR_PANE_ID HERDR_TAB_ID HERDR_WORKSPACE_ID HERDR_SOCKET_PATH TMUX
cat > "$AREA/shim/herdr" <<'SH'
#!/usr/bin/env bash
set -eu
if [ "${1:-}" = --version ]; then
  PATH="$ORIGINAL_PATH" "$HELPER" run "$SESSION" status --json | jq -r '"herdr " + .client.version'
  exit
fi
args=("$@")
n=${#args[@]}
if [ "$n" -ge 2 ] && [ "${args[n-2]}" = --session ]; then
  [ "${args[n-1]}" = "$SESSION" ] || exit 97
  unset 'args[n-1]' 'args[n-2]'
fi
exec env PATH="$ORIGINAL_PATH" "$HELPER" run "$SESSION" "${args[@]}"
SH
chmod +x "$AREA/shim/herdr"
export PATH="$AREA/shim:$PATH"
. bin/fm-backend.sh
fm_backend_source herdr
raw=$(fm_backend_herdr_container_ensure "$AREA")
container=${raw%%$'\t'*}
seed=${raw#*$'\t'}
read -r tab pane <<< "$(fm_backend_herdr_create_task "$container" fm-proof "$AREA" "$seed")"
target="$SESSION:$pane"
printf 'Created endpoint %s in %s\n' "$target" "$container"
for attempt in {1..30}; do
  fm_backend_herdr_send_text_line "$target" "printf 'shell-%s\\n' ready > '$AREA/ready'"
  sleep 0.2
  [ ! -f "$AREA/ready" ] || break
done
[ "$(cat "$AREA/ready")" = shell-ready ]
fm_backend_herdr_send_literal "$target" "printf 'literal-%s\\n' delivered > '$AREA/literal'"
sleep 0.5
[ ! -e "$AREA/literal" ]
fm_backend_herdr_send_key "$target" Enter
for attempt in {1..30}; do [ ! -f "$AREA/literal" ] || break; sleep 0.1; done
[ "$(cat "$AREA/literal")" = literal-delivered ]
printf 'Literal input stayed unsubmitted until Enter, then wrote: %s\n' "$(cat "$AREA/literal")"
payload=$(python3 -c 'print("abc123" * 4000)')
fm_backend_herdr_send_text_line "$target" "printf '%s' '$payload' > '$AREA/long'"
for attempt in {1..50}; do [ ! -s "$AREA/long" ] || break; sleep 0.1; done
[ "$(wc -c < "$AREA/long" | tr -d ' ')" = 24000 ]
python3 - "$AREA/long" <<'PY'
import hashlib, pathlib, sys
actual = pathlib.Path(sys.argv[1]).read_bytes()
assert actual == b'abc123' * 4000
print('Long command executed, exact bytes:', len(actual), 'SHA256:', hashlib.sha256(actual).hexdigest())
PY
fm_backend_herdr_send_text_line "$target" "printf 'capture-%s\\n' verified"
sleep 0.4
fm_backend_herdr_capture "$target" 12
fm_backend_herdr_kill "$target"
if fm_backend_target_exists herdr "$target"; then echo 'Deleted endpoint still exists'; exit 1; fi
echo 'Deleted endpoint is absent. Teardown must preserve the default-session tripwire.'
