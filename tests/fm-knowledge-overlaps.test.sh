#!/usr/bin/env bash
# tests/fm-knowledge-overlaps.test.sh - live lane-overlap detection
# (bin/fm-knowledge.sh overlaps; contract: docs/crew-knowledge.md).
#
# overlaps reads every state/<id>.meta with a worktree= (skipping
# kind=secondmate), diffs the worktree against its default-branch base with
# `git diff --name-only <base>`, and reports lane pairs in the same project
# that share an exact path or a top-level directory. These tests build real
# git worktrees and pin:
#   1. Two lanes in the same project touching the same top-level directory
#      are reported as an overlap pair.
#   2. Two lanes in the same project touching the same file are reported with
#      the shared file named.
#   3. Lanes in different projects never pair, even on identical paths.
#   4. kind=secondmate metas are skipped.
#   5. A lane whose worktree cannot be diffed is reported unreadable instead
#      of breaking the run.
#   6. A lane with no changes is reported clean and pairs with nobody.
set -u

# shellcheck source=tests/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

KNOW="$ROOT/bin/fm-knowledge.sh"
fm_git_identity

TMP_ROOT=$(fm_test_tmproot fm-knowledge-overlaps)
TMP_ROOT=$(cd "$TMP_ROOT" && pwd)

# Build <name> home with a project repo and two worktree lanes whose staged
# file lists come from the arguments.
setup_lanes() {  # <name> <lane-a-files...> -- <lane-b-files...>
  local name=$1; shift
  local home="$TMP_ROOT/$name" repo wt_a wt_b f
  home="$TMP_ROOT/$name"
  mkdir -p "$home/state"
  repo="$home/repo"
  fm_git_worktree "$repo" "$home/wt-a" lane-a
  # The second lane reuses the same repo: worktree-add directly rather than
  # fm_git_worktree, which would re-init the repo and leak git's
  # nothing-to-commit noise into the captured home path.
  git -C "$repo" worktree add --quiet -b lane-b "$home/wt-b"
  wt_a="$home/wt-a"; wt_b="$home/wt-b"
  while [ $# -gt 0 ] && [ "$1" != "--" ]; do
    f=$1; shift
    [ -n "$f" ] || continue
    mkdir -p "$wt_a/$(dirname "$f")"
    printf 'change a\n' > "$wt_a/$f"
    git -C "$wt_a" add -A >/dev/null 2>&1
  done
  shift
  while [ $# -gt 0 ]; do
    f=$1; shift
    [ -n "$f" ] || continue
    mkdir -p "$wt_b/$(dirname "$f")"
    printf 'change b\n' > "$wt_b/$f"
    git -C "$wt_b" add -A >/dev/null 2>&1
  done
  fm_write_meta "$home/state/fm-lane-a.meta" "kind=crewmate" "worktree=$wt_a" "project=$repo"
  fm_write_meta "$home/state/fm-lane-b.meta" "kind=crewmate" "worktree=$wt_b" "project=$repo"
  printf '%s\n' "$home"
}

test_same_dir_overlap_detected() {
  local home out
  home=$(setup_lanes samedir src/billing/api.c src/auth/login.c -- src/billing/tax.c)
  out=$(FM_HOME="$home" "$KNOW" overlaps) || fail "overlaps failed"
  assert_contains "$out" "fm-lane-a + fm-lane-b" "same-project lanes sharing src/ must pair"
  assert_contains "$out" "shared top-level dirs: src/" "the shared top-level dir should be named"
  pass "overlaps: same-project lanes sharing a top-level directory are paired"
}

test_same_file_overlap_named() {
  local home out
  home=$(setup_lanes samefile src/billing/api.c -- src/billing/api.c src/other.c)
  out=$(FM_HOME="$home" "$KNOW" overlaps) || fail "overlaps failed"
  assert_contains "$out" "shared files: src/billing/api.c" "the shared file should be named"
  pass "overlaps: same-project lanes sharing an exact file are paired with the file named"
}

test_cross_project_never_pairs() {
  local home out repo_b
  home=$(setup_lanes crossproj src/billing/api.c -- src/billing/api.c)
  # Point lane b's meta at a different project path.
  repo_b="$home/other-repo"
  fm_write_meta "$home/state/fm-lane-b.meta" "kind=crewmate" "worktree=$home/wt-b" "project=$repo_b"
  out=$(FM_HOME="$home" "$KNOW" overlaps) || fail "overlaps failed"
  assert_contains "$out" "no overlapping lanes" "different projects must never pair"
  pass "overlaps: identical paths in different projects never pair"
}

test_secondmate_meta_is_skipped() {
  local home out
  home=$(setup_lanes sm src/a.c -- src/a.c)
  fm_write_meta "$home/state/fm-lane-b.meta" "kind=secondmate" "worktree=$home/wt-b" "project=$home/repo"
  out=$(FM_HOME="$home" "$KNOW" overlaps) || fail "overlaps failed"
  case "$out" in *fm-lane-b*) fail "a secondmate meta must be skipped: $out" ;; esac
  pass "overlaps: kind=secondmate metas are skipped"
}

test_unreadable_lane_reported_not_fatal() {
  local home out
  home=$(setup_lanes unread src/a.c -- src/a.c)
  rm -rf "$home/wt-b"
  mkdir "$home/wt-b"   # exists, but not a git worktree
  out=$(FM_HOME="$home" "$KNOW" overlaps) || fail "an unreadable lane must not fail the run"
  case "$out" in *fm-lane-b*) fail "a non-git worktree should be skipped, not probed: $out" ;; esac
  # A git worktree whose base ref is gone is unreadable but listed.
  fm_write_meta "$home/state/fm-lane-c.meta" "kind=crewmate" "worktree=$home/wt-a" "project=$home/repo"
  out=$(FM_HOME="$home" FM_KNOWLEDGE_OVERLAP_MAX_LANES=1 "$KNOW" overlaps) || fail "overlaps with cap failed"
  assert_contains "$out" "not probed" "the lane cap should disclose skipped lanes"
  pass "overlaps: unreadable lanes never break the run and the lane cap is disclosed"
}

test_clean_lane_pairs_with_nobody() {
  local home out
  home=$(setup_lanes clean "" -- "")
  # Empty file lists: remove the placeholder writes by resetting the index.
  git -C "$home/wt-a" reset -q >/dev/null 2>&1 || true
  git -C "$home/wt-b" reset -q >/dev/null 2>&1 || true
  out=$(FM_HOME="$home" "$KNOW" overlaps) || fail "overlaps failed"
  assert_contains "$out" "no changes" "an unchanged lane should report clean"
  assert_contains "$out" "no overlapping lanes" "clean lanes must not pair"
  pass "overlaps: a lane with no changes is clean and pairs with nobody"
}

test_same_dir_overlap_detected
test_same_file_overlap_named
test_cross_project_never_pairs
test_secondmate_meta_is_skipped
test_unreadable_lane_reported_not_fatal
test_clean_lane_pairs_with_nobody
