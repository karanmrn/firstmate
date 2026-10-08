#!/usr/bin/env bash
# Token-free installed native app-server hook and ownership guard.
set -u
# shellcheck source=tests/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
fm_live_gate default-on FM_CODEX_SESSION_IDENTITY_LIVE codex
python3 "$ROOT/tests/fm-codex-session-lock-repro.py" --live
