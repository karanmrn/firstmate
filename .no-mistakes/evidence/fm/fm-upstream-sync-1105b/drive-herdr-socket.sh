#!/usr/bin/env bash
set -eu
root=$PWD
export FM_HERDR_LAB_STATE_DIR="$root/.validation-sync/herdr-state"
session=$(cat .validation-sync/herdr-session)
cleanup() { "$root/bin/fm-herdr-lab.sh" teardown "$session"; }
trap cleanup EXIT
"$root/bin/fm-herdr-lab.sh" provision "$session"
"$root/bin/fm-herdr-lab.sh" run "$session" status --json
sessions=$("$root/bin/fm-herdr-lab.sh" run "$session" session list --json)
socket=$(printf '%s' "$sessions" | jq -er --arg s "$session" '.sessions[] | select(.name==$s and .running==true and .default==false) | .socket_path')
printf 'Live lab session: %s\nReported socket: %s\n' "$session" "$socket"
[ -S "$socket" ]
. "$root/bin/backends/herdr.sh"
fm_backend_herdr_cli() { "$root/bin/fm-herdr-lab.sh" run "$@"; }
canonical=$(fm_backend_herdr_presentation_session_socket_path "$session")
printf 'Firstmate session identity: %s\n' "$canonical"
[ -S "$canonical" ]
ln -s "$(dirname "$socket")" "$root/.validation-sync/socket-alias"
alias_id=$(fm_backend_herdr_canonical_socket_path "$root/.validation-sync/socket-alias/$(basename "$socket")")
printf 'Identity through symlinked parent: %s\n' "$alias_id"
[ "$canonical" = "$alias_id" ]
for invalid in '' relative.sock 'C:\missing\herdr.sock' 'C:/missing/herdr.sock'; do
  if got=$(fm_backend_herdr_canonical_socket_path "$invalid"); then
    printf 'Unexpected accepted identity: %s\n' "$got"; exit 1
  else
    printf 'Refused invalid or unconvertible socket identity: <%s>\n' "$invalid"
  fi
done
printf 'Live Unix socket equality and refusal checks passed.\n'
