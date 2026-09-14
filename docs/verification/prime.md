# Verification: the prime (Prime Agent) crewmate adapter

Active empirical evidence for firstmate's prime adapter.
The skill tree rooted at [`.agents/skills/harness-adapters/SKILL.md`](../../.agents/skills/harness-adapters/SKILL.md) owns the operating facts; this record owns how they were established and what is still unproven.

## Subject

| Field | Value |
|---|---|
| Version | `prime-agent --version` printed `0.9.4` on stderr |
| Backend | Herdr 0.9.0, isolated lab sessions from `bin/fm-herdr-lab.sh` |
| Provider | `openrouter`, model `moonshotai/kimi-k2.6` |
| Verified | 2026-09-14 |
| Platform | macOS arm64 (Darwin 25.6.0) |

## Live guard

The guard runs the real `prime-agent` with the launch command and extension that `bin/fm-spawn.sh` composes, inside an isolated Herdr lab session, and spends two short model turns:

```sh
FM_PRIME_HERDR_LIVE=1 HERDR_LAB_HELPER=bin/fm-herdr-lab.sh \
  tests/fm-prime-herdr-live-e2e.test.sh
```

Observed output on 2026-09-14:

```text
# prime-agent 0.9.4 at /Users/<user>/.local/bin/prime-agent
# herdr 0.9.0
# model openrouter/moonshotai/kimi-k2.6
ok - real herdr: detects the Prime pane natively as agent prime-agent
ok - real prime-agent: a tool beside PI_CODING_AGENT=true detects harness prime
ok - real prime-agent: the generated extension settles the turn idle and touches the turn-end marker
ok - real prime-agent: one Ctrl+C cancels the run, keeps the agent, and settles idle
ok - real prime-agent: /quit ends the client-owned worker and its Python kernel
```

Run it after every Prime Agent or Herdr upgrade.
The portable regressions are `tests/fm-prime-harness.test.sh`, the Prime cases in `tests/fm-busy-adapter-wiring.test.sh`, and `test_prime_control_table` in `tests/fm-control.test.sh`.

## Environment marker

A print-mode probe ran one `ipython` tool call that printed the names of the identity-shaped variables and the process ancestry, with values shown only for the marker variables:

```sh
env -u CLAUDECODE FM_PROBE_SENTINEL=launch-a1 \
  prime-agent -p --mode json --no-skills --no-session '<ipython probe>'
```

The tool result contained `'FM_PROBE_SENTINEL': 'launch-a1'`, `'PI_CODING_AGENT': 'true'`, and set values for `PRIME_AGENT_KERNEL_OWNER_PID` and `PRIME_AGENT_INTERNAL_DAEMON_WORKER`.
The ancestry was `kernel-venv/bin/python`, then three `prime-agent` processes: the session worker, the daemon supervisor, and the client.
In the installed package, `dist/cli-main.js` runs `process.env.PI_CODING_AGENT = "true"` at startup, and `dist/core/kernel/repl-manager.js` adds `PRIME_AGENT_KERNEL_OWNER_PID` to the kernel environment.
The interactive probe logged `sentinel=tui-b2` from the extension's worker process, so launch environment variables also reach a TUI session's worker.

## Skills prompt budget

Each row is the first assistant message's `input` plus `cacheRead` tokens for the same one-line prompt, with `~/.agents/skills` holding 480 `SKILL.md` files:

```sh
prime-agent -p --mode json --no-session [--no-skills] 'Reply with the single word OK.'
```

| Launch directory | Skill discovery | Prompt tokens |
|---|---|---|
| Firstmate task worktree | default | 60,159 |
| Firstmate task worktree | `--no-skills` | 18,114 |
| `$HOME` | default | 41,433 |
| `$HOME` | `--no-skills` | 2,604 |

The remaining worktree cost under `--no-skills` is the project's own `AGENTS.md` context.
On 2026-09-13 the same host held 3063 skills, and a default launch from `$HOME` failed with `400 This endpoint's maximum context length is 262144 tokens. However, you requested about 398740 tokens`.

## Effort

`get_state` over RPC reports the thinking level each `--thinking` value produced, with no model call:

```sh
printf '{"type":"get_state"}\n' | prime-agent --mode rpc --no-skills --no-session \
  --model openrouter/moonshotai/kimi-k2.6 --thinking <level>
```

For kimi-k2.6, `off` reported `off` and every other level, including an omitted flag, reported `high`.
The same command with `--model openrouter/anthropic/claude-fable-5.1 --thinking low` reported `low`, so Prime clamps to each model's supported levels rather than ignoring the flag.

## Daemon lifecycle

Interactive probes ran in isolated Herdr lab panes and read `prime-agent list --all --json`, process lists, and an event-logging extension:

| Case | Observation |
|---|---|
| Resident session, `/quit` | The pane closed; the session stayed `live` with its worker and Python kernel running. |
| Resident session, `prime-agent stop <id>` with the TUI attached | `stop` printed `ok`; the TUI stayed open on `Error: The daemon stopped this agent session.` |
| Resident session, `prime-agent -c` in the same directory | The previous transcript reopened. |
| `--no-session`, `/quit` | The worker process was gone after 2 seconds. |
| `--no-session`, pane closed without quitting | The worker process was gone after 31 seconds. |
| Saved idle session, `prime-agent stop <id>` | `Error: Unknown active session: <id>` until the session was resumed. |

## Busy-state events

The event-logging extension recorded, for a one-tool turn, `agent_start` with `ctx.isIdle()` false, two `turn_end` events, and `agent_end` with `ctx.isIdle()` still false.
A poll started from `agent_end` read `ctx.isIdle()` true after 9 milliseconds in one run and 7 milliseconds in another.
The package emits no `agent_settled` event: the bundle has no such string.

## Interrupt, composer, and Herdr detection

- One Ctrl+C during a running `ipython` call marked the call failed, fired `agent_end`, and left the TUI running.
- One Ctrl+C on an idle composer showed `Press Ctrl+C again to exit` for a few seconds, then cleared; the agent stayed alive.
- Escape left a typed draft in the composer.
- The idle composer is a bare ` >  ` row on background `48;2;26;26;31` with the placeholder `Try "refactor @<filepath>"` in `38;2;113;113;122`.
- `herdr agent get` returned `"agent":"prime-agent"` with `working` during a turn and `idle` after it, for resident and `--no-session` panes alike.
- No trust dialog appeared in fresh git directories.

## Not verified

- tmux was not installed on the verification host, so Prime's tmux liveness naming, tmux composer submit confirmation, and tmux control-plane attribution are unproven; the tmux control fake reads a Prime pane as ambiguous and refuses lifecycle verbs.
- Zellij, cmux, and Orca were not exercised.
- Providers other than `openrouter` and models other than kimi-k2.6 and claude-fable-5.1 were not exercised.
- Behavior without provider credentials was not exercised.
- Runs longer than the extension's 30-second idle poll after `agent_end`, such as automatic compaction, were not exercised.
- A Prime primary or secondmate integration does not exist.
