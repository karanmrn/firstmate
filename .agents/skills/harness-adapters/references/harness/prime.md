# Prime Agent

Verified on 2026-09-14 with Prime Agent 0.9.4 on the Herdr 0.9.0 backend, driving the `openrouter` provider.
The router owns Prime's task-kind boundary.
`../../../docs/verification/prime.md` owns the commands, measurements, and remaining gaps.

## Operating facts

| Fact | Value |
|---|---|
| Binary | Absolute `prime-agent` from `PATH`, refused if absent; the client, daemon supervisor, and session worker all carry process title `prime-agent`. |
| Launch | Positional instructions with `--no-skills --no-session -e <state>/<id>.prime-ext.ts`. |
| Subcommands | Put the subcommand first, as in `prime-agent model list openrouter`; a global option before a subcommand turns the subcommand into prompt text and starts a model turn. |
| Autonomy | No approval gate; the single `ipython` tool ran commands without a prompt. |
| Trust dialog | None observed in fresh git directories. |
| Models | `--model <provider>/<id>`, for example `openrouter/moonshotai/kimi-k2.6`; discover with `prime-agent model list [search]`. |
| Effort | `--thinking <low\|medium\|high\|xhigh\|max>`; Prime clamps each request to the model's supported levels, so kimi-k2.6 reports `high` for every level except `off`. |
| Busy state | The Firstmate-owned extension: `agent_start` marks busy, idle follows `agent_end` only after `ctx.isIdle()` reads true, and `session_shutdown` closes an open run. |
| Interrupt | Single Ctrl+C cancels the run and keeps the TUI; a second Ctrl+C while `Press Ctrl+C again to exit` shows quits. |
| Escape | Edits the composer only: it neither interrupts nor cleared a typed draft. |
| Exit | `/quit`. |
| Resume | None for Firstmate workers, because `--no-session` keeps no transcript; recovery relaunches from the instructions. |
| Skill invocation | `/skill:<name>` exists, but `--no-skills` removes discovery, so use natural language. |
| Environment marker | `PRIME_AGENT_KERNEL_OWNER_PID` in tool processes or `PRIME_AGENT_INTERNAL_DAEMON_WORKER` in the worker; Prime also sets `PI_CODING_AGENT=true`, so `../../../bin/fm-harness.sh` tests Prime first. |
| Herdr state | Herdr 0.9.0 detects the pane as agent `prime-agent` with working and idle states, so no `herdr pane report-agent` call is needed. |
| Composer | A bare `>` row on a dark background block with a `Try "..."` placeholder in truecolor `38;2;113;113;122`; the shell-glyph safety rule reads it unknown, so submit confirmation rides Herdr's native idle-to-working edge. |

## Daemon lifecycle

Prime runs every session in a daemon worker process, and the pane's TUI is only a client attached to it.
A resident session, the default, survives `/quit` and a closed pane with its worker and Python kernel still running.
`prime-agent stop <id>` ends a resident worker but leaves an attached TUI open on an error banner.
`--no-session` makes the worker client-owned, so it ends with its TUI: 2 seconds after `/quit` and 31 seconds after the pane closed.
That is why Firstmate launches with `--no-session` and treats the pane as the whole lifecycle.
Resident `prime-agent -c` reopens the directory's latest session, but Firstmate does not use it.
`prime-agent stop` accepts only a live session; a saved idle session answers `Unknown active session` until it is resumed.
Launch environment variables reach the worker and every tool process.

## Worker extension

`../../../bin/fm-spawn.sh` writes the extension to `state/`, outside the worktree, and loads it with `-e`.
Prime 0.9.4 has no `agent_settled` event, and `ctx.isIdle()` still reads false inside `agent_end`, so the extension polls after `agent_end` instead of settling there.
`turn_end` touches the turn-ended marker as a wake notification, never as current state.

## Skills budget

Skill discovery reads `~/.agents/skills` and every ancestor `.agents/skills`, and puts each skill's name and description into the startup prompt.
A large global skill set once pushed that prompt past kimi-k2.6's 262k-token window, which is why every Firstmate launch passes `--no-skills`.

## Primary limit and backend coverage

No Prime primary integration exists, so `../../../bin/fm-spawn.sh` refuses a secondmate on Prime.
tmux was not installed on the verification host, so tmux liveness naming and tmux submit confirmation for Prime remain unverified.
