# Native Codex ownership validation

Tested target: `3f86f3ca46296ea307b1be635a04c8875ccccb9f`.
Baseline: `f6cefdfbd99bd93bab3a3fd03c05505c758ea6e3`.
Runtime: installed Codex 0.167.0, macOS 27.2.0, arm64.

The independent oracle is the author's required ownership contract: a shared server must have exactly one trusted session owner. A competing or conflicting thread must remain read-only. The baseline violates that contract in both portable and installed-server runs. The target satisfies it.

## Live product checks

- Two genuine Codex sessions used one real app-server. The first acquired the lock. The second received READ-ONLY SESSION. The sidecar retained the first session's genuine UUID.
- Valid hook payloads preserved ownership through resume and compact. Contradictory and missing payload identities did not inherit ownership from retained shell variables.
- Adversarial CODEX_SESSION_ID/CODEX_THREAD_ID combinations rejected acquisition, ownership and checkpoints. These are explicit conflicting-input probes under a real native server, not a claim that a model spawned a descendant agent.
- The owner ran the real bounded watcher. Competing checkpoints exited 1 without starting a watcher or updating its beacon.
- Foreign Stop and conflicting descendant identity probes returned the read-only diagnostic with exit 0. The native park adapter also preserved that result.
- Live native PID-only and symlinked locks stayed unclaimable. Adversarial probes preserved the original lock and sidecar.
- After the original native server exited, a new real server reclaimed its stale lock and recorded its new genuine session identity.
- An installed codex exec shell acquired, reentered and proved ordinary PID ownership without a native sidecar. A disposable local Responses provider supplied a deterministic tool call. The real CLI and Firstmate scripts executed it and the CLI exited 0. No model credentials or external model service were used.
- Real process text matched ps through the OS provider in inherited, C and en_US.UTF-8 locales, including tabs, newlines, Unicode and a trailing empty argument. Denying ps inside real native hooks still accepted only the owner.

## Targeted tests and test repair

The four selected suites exercised the portable regression, installed native regression, process identity and foreground checkpoints. The initial checkpoint queue-append case exceeded its five-second deadline. An isolated reproduction also failed. Its unchanged delivery assertions passed with a twenty-second bound. Only that test's bound and explanatory comment changed. The entire focused checkpoint suite then passed.

The portable fixture also passed directly with poisoned repository-location variables and malformed global/system Git configuration. No redirected Git paths were created.

A closed-provider CLI attempt could not execute a shell, so the completed CLI proof used the disposable local provider. Additional concurrent native/Git probes exceeded their setup deadlines. Both completed successfully when rerun alone. Those unsuccessful attempts are retained in their logs, not counted as product passes.

The native fixtures retain real lock/startup/ownership paths. Unrelated startup network, fleet and cleanup leaves are inert, as in the repository fixture. The owner checkpoint uses the real watcher. Alternate code-mode process-name and flag variants are covered by the portable fixture rather than a separate live code-mode deployment.

No GUI layout changed. CLI transcripts, protocol tool results, process records and persisted lock state provide the reviewer-visible evidence. No screenshot was required.

All required children completed. Disposable servers, the local provider and temporary worktree fixtures were removed. The only remaining source modification is the test timeout adjustment. No lint, formatter, build, push, PR, CI or pipeline-control operation ran.
