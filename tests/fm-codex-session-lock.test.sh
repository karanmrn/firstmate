#!/usr/bin/env bash
# Native Codex shared-server lock regression through isolated primary homes.
set -u
# shellcheck source=tests/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
python3 "$ROOT/tests/fm-codex-session-lock-repro.py"
