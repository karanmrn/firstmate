# macOS test portability validation

Target: e320dee2e3601ca209904e32d810c4e0bda2bc81
Base: 65a9a51f099e91c5e2d05c9ae9c3d5e493d51762
Host: Darwin arm64. The tests ran with /bin/bash 3.2.57 and /usr/bin/jq. No setsid executable was available on PATH.

The diff changes only four test scripts and tests/lib.sh. There is no changed runtime product behaviour. These results are fixture-based targeted checks, not live Herdr or harness acceptance.

| Check | Base result | Target result |
| --- | --- | --- |
| Remote doctor suite | Exit 1. The repairable-host case remained unready. | Exit 0. The full selected suite completed. |
| Remote Herdr guard suite | Exit 1. The system jq holder exposed no marker environment. | Exit 0. Marker proof, foreign owners, bounded refusal and delayed release checks completed. |
| OMP detection and marker precedence | Exit 1. The leaked marker case returned codex rather than claude under this runner. | Exit 0. Anchored identity, decoys and marker precedence checks completed. |
| Process-event draining re-arm | Exit 1. setsid was absent and the holder identity could not be read. | Exit 0. The staged reply preceded readiness and the next generation started after claim release. |

The two remote scripts ran in full. The OMP check executed the unchanged setup and test_detection_anchored_name_and_marker_precedence function from each revision. The process-event check executed the unchanged setup helpers, wait_for_lines helper and draining-rearm block from each revision. Temporary runners only adjusted test-library locations to the current worktree. They did not change assertions or product behaviour.

The independent oracles are the author's portability requirements and the existing executable contracts: marker visibility must distinguish owner birth, an unrelated outer Codex process must not change the local Claude case, and releasing an old claim must allow a new listener and exactly one staged reply. The base runs reject each reported wrong behaviour.

Commands:

- env TMPDIR="$PWD/.portability-check/tmp" /bin/bash tests/fm-remote-doctor.test.sh
- env TMPDIR="$PWD/.portability-check/tmp" /bin/bash tests/fm-remote-herdr-guard.test.sh
- env TMPDIR="$PWD/.portability-check/tmp" /bin/bash .portability-check/target-omp-detection.sh
- env TMPDIR="$PWD/.portability-check/tmp" /bin/bash .portability-check/draining-rearm.sh
- Corresponding base-revision runners for all four checks.

Each command completed and its actual exit status was inspected. Expected base failures are regression evidence, not target failures. The complete repository suite, builds, linters and formatters were not run. No GUI changed, so screenshots do not apply. Test fixtures and temporary runners were removed. No source changes were needed.
