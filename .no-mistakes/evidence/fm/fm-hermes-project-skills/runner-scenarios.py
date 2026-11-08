import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path.cwd()
evidence = Path(__file__).parent
fixture = Path(tempfile.mkdtemp(prefix=".nm-runner-live-", dir=root))
env = dict(os.environ)
for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "FM_TASK_ID"):
    env.pop(key, None)
env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
transcript = []

def run(args, expected=0, label=None):
    result = subprocess.run(args, cwd=fixture, env=env, text=True, capture_output=True)
    if label:
        transcript.extend(["## " + label, "$ " + " ".join(args), result.stdout, result.stderr, "exit=" + str(result.returncode)])
    assert result.returncode == expected, (args, result.returncode, result.stdout, result.stderr)
    return result

def commit():
    run(["git", "add", "."])
    run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "fixture"])

def runner(label, expected=0, listing=False):
    args = ["bin/fm-test-run.sh", "--changed", "--base", "HEAD"]
    if listing:
        args.append("--list")
    elif expected == 0:
        args.extend(["--json", str(evidence / (label + ".json"))])
    return run(args, expected, label)

try:
    (fixture / "bin").mkdir()
    (fixture / "tests").mkdir()
    for relative in ("bin/fm-test-run.sh", "bin/fm-timeout-lib.sh", "tests/git-config-helpers.sh", "tests/fm-ask-user-authority.test.sh"):
        shutil.copy2(root / relative, fixture / relative)
    run(["git", "init", "-q"])
    commit()
    skill = fixture / ".agents/skills/disposable"
    skill.mkdir(parents=True)
    license_file = skill / "LICENSE"
    license_file.write_text("MIT License\n")
    # Independent oracle: a licence-only change has no runnable behaviour.
    result = runner("license-added")
    doc = json.loads((evidence / "license-added.json").read_text())
    assert doc["scripts"] == [] and doc["summary"]["total"] == 0
    target = (root / "bin/fm-test-run.sh").read_bytes()
    baseline = subprocess.run(["git", "show", "03f0bb07a55e6984f91bb11f4425fc562bb959df:bin/fm-test-run.sh"], cwd=root, env=env, capture_output=True, check=True).stdout
    (fixture / "bin/fm-test-run.sh").write_bytes(baseline)
    # Keep the runner itself out of changed selection during baseline comparison.
    run(["git", "add", "bin/fm-test-run.sh"])
    run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", "commit", "-qm", "baseline-runner"])
    old = runner("baseline-license-added", expected=2)
    assert "no changed-test mapping for source path: .agents/skills/disposable/LICENSE" in old.stderr
    (fixture / "bin/fm-test-run.sh").write_bytes(target)
    commit()
    license_file.write_text("MIT License\nCopyright fixture\n")
    runner("license-modified")
    assert json.loads((evidence / "license-modified.json").read_text())["scripts"] == []
    commit()
    license_file.unlink()
    runner("license-deleted")
    assert json.loads((evidence / "license-deleted.json").read_text())["scripts"] == []
    run(["git", "restore", ".agents/skills/disposable/LICENSE"])
    (skill / "SKILL.md").write_text("---\nname: disposable\ndescription: Disposable skill data.\n---\n")
    license_file.write_text("MIT License\nUpdated alongside instructions\n")
    result = runner("skill-with-license", listing=True)
    assert result.stdout.splitlines() == ["tests/fm-ask-user-authority.test.sh"]
    (skill / "SKILL.md").unlink()
    run(["git", "restore", ".agents/skills/disposable/LICENSE"])
    (skill / "tool.sh").write_text("#!/bin/sh\nexit 0\n")
    result = runner("nonlicense-refused", expected=2, listing=True)
    assert "no changed-test mapping for source path: .agents/skills/disposable/tool.sh" in result.stderr
    (skill / "tool.sh").unlink()
    unrelated = fixture / ".agents/unrelated/LICENSE"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("MIT License\n")
    result = runner("outside-skill-license-refused", expected=2, listing=True)
    assert "no changed-test mapping for source path: .agents/unrelated/LICENSE" in result.stderr
    transcript.append("All runner scenario assertions passed.")
finally:
    shutil.rmtree(fixture)
    (evidence / "runner-transcript.txt").write_text("\n".join(transcript) + "\n")
