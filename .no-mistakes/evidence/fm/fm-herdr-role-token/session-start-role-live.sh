#!/usr/bin/env bash
# Live check: real bin/fm-session-start.sh, run inside a real Herdr pane of an
# isolated fm-lab- session, reports the pane's fleet role token.
set -u
ROOT=${ROOT:?}
LAB="$ROOT/bin/fm-herdr-lab.sh"
T=$(mktemp -d "$(cd "${TMPDIR:-/tmp}" && pwd -P)/fm-role-live.XXXXXX")
S=$("$LAB" name role-live) || exit 1
echo "lab session: $S"
cleanup() { "$LAB" teardown "$S"; rm -rf "$T"; }
trap cleanup EXIT
"$LAB" provision "$S" || { echo "provision failed"; exit 1; }
lab() { "$LAB" run "$S" "$@"; }
role_of() { lab pane get "$1" 2>/dev/null | jq -c '.result.pane.tokens // {}'; }

out=$(lab workspace create --cwd "$T" --label roletest --no-focus) || { echo "workspace create failed"; exit 1; }
PANE=$(printf '%s' "$out" | jq -r '.result.root_pane.pane_id')
echo "pane: $PANE"
echo "tokens before any session start: $(role_of "$PANE")"

mkdir -p "$T/primary/state" "$T/primary/data" "$T/primary/config"
mkdir -p "$T/second/state" "$T/second/data" "$T/second/config"
printf 'sm1\n' > "$T/second/.fm-secondmate-home"
mkdir -p "$T/foreign/state" "$T/foreign/data" "$T/foreign/config"

cat > "$T/in-pane.sh" <<SH
#!/usr/bin/env bash
run() {  # <label> <home> [env...]
  local label=\$1 home=\$2; shift 2
  env | grep '^HERDR_' | sort > "$T/\$label.env"
  # A bash whose argv[0] is "claude" stands in as the harness process, so the
  # session lock is really acquired and the locked bootstrap path runs.
  env -u CLAUDECODE -u PI_CODING_AGENT -u FM_PI_HARNESS -u GROK_AGENT "\$@" FM_HOME="\$home" \
    bash -c 'exec -a claude /bin/bash -c "\$@"' _ \
    'timeout 240 "\$0" > "\$1" 2>&1; echo \$? > "\$2"' \
    "$ROOT/bin/fm-session-start.sh" "$T/\$label.out" "$T/\$label.rc"
}
case "\$1" in
  foreign) run foreign "$T/foreign" HERDR_SESSION=fm-lab-notthisone ;;
  primary) run primary "$T/primary" ;;
  second)  run second "$T/second" ;;
esac
SH
chmod +x "$T/in-pane.sh"

drive() {  # <variant>
  lab pane run "$PANE" "$T/in-pane.sh $1" >/dev/null 2>&1 || { echo "pane run failed for $1"; return 1; }
  local i=0
  while [ ! -f "$T/$1.rc" ] && [ "$i" -lt 150 ]; do sleep 2; i=$((i + 1)); done
  echo "== $1: session start exit=$(cat "$T/$1.rc" 2>/dev/null || echo timeout)"
  echo "   injected env: $(tr '\n' ' ' < "$T/$1.env" 2>/dev/null)"
  echo "   role warnings in session start output:"
  grep -i "role token" "$T/$1.out" | sed 's/^/     /'
  echo "   pane tokens after: $(role_of "$PANE")"
  cp "$T/$1.out" "${EV:-$T}/session-start-$1.out" 2>/dev/null || true
}

drive foreign
drive primary
drive second
echo "== herdr pane get $PANE (final):"
lab pane get "$PANE" | jq '.result.pane | {pane_id, workspace_id, tokens}'
