#!/usr/bin/env python3
"""Exercise actual startup, acquisition, ownership and Stop in a temporary home.

Only the vendor process-table boundary is simulated. The server's real PID is
shared by every invocation. UUIDs are fixture inputs, never live identity proof.
"""
import json
import os
import select
import signal
import sys
import time
import pathlib
import shutil
import subprocess
import tempfile

REPO = pathlib.Path('~/.no-mistakes/worktrees/48f6cc4ba3af/01M6RF5MKEHX33BP21ENCYD6C0')
OWNER = '00000000-0000-4000-8000-000000000001'
OTHER = '00000000-0000-4000-8000-000000000002'
BASE = {k: v for k, v in os.environ.items() if not k.startswith(
    ('FM_', 'CODEX_', 'CLAUDE_', 'HERDR_', 'TASKS_AXI_', 'CURSOR_', 'PI_'))}
for name in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR'):
    BASE.pop(name, None)
BASE.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
PS = shutil.which('ps')

with tempfile.TemporaryDirectory(prefix='.fm-live-validation-', dir=REPO) as temp:
    home = pathlib.Path(temp)
    for name in ('state', 'data', 'config', 'projects', 'fakebin'):
        (home / name).mkdir()
    shutil.copytree(REPO / 'bin', home / 'bin')
    (home / 'AGENTS.md').write_text('Isolated fixture.\n')
    subprocess.run(['git', 'init', '-q', str(home)], env=BASE, check=True)
    # Startup composition remains real. External fleet, network and cleanup
    # leaves cannot run infrastructure commands, even against an empty home.
    for name in ('fm-bootstrap.sh', 'fm-herdr-session-cleanup.sh',
                 'fm-startup-network.sh', 'fm-home-summary-refresh.sh',
                 'fm-guard.sh', 'fm-lease.sh', 'fm-branch-outcome.sh',
                 'fm-public-followup.sh'):
        (home / 'bin' / name).write_text('#!/usr/bin/env bash\nexit 0\n')
    (home / 'fakebin' / 'ps').write_text(f'''#!/usr/bin/env bash
if [ "$*" = '-o comm= -p {os.getpid()}' ]; then printf '%s\\n' "${{FM_FIXTURE_COMM:-/opt/codex}}"; exit 0; fi
if [ "$*" = '-o args= -p {os.getpid()}' ]; then printf '%s\\n' "${{FM_FIXTURE_ARGV0:-/opt/codex}} ${{FM_FIXTURE_SUBCOMMAND:-app-server}} --listen stdio://"; exit 0; fi
exec '{PS}' "$@"
''')
    (home / 'fakebin' / 'ps').chmod(0o755)
    if '--live' not in sys.argv: (home / 'bin/fm-watch.sh').write_text('#!/usr/bin/env bash\ntouch "$FM_HOME/state/checkpoint-ran"\nprintf "signal: fixture\\n"\n')
    (home / '.codex').mkdir()
    shutil.copy(REPO / '.codex/hooks.json', home / '.codex/hooks.json')
    env = BASE | {'FM_HOME': str(home), 'FM_ROOT_OVERRIDE': str(home),
                  'FM_SESSION_START_STAGE_FILE': str(home / 'state/stage'),
                  'PATH': str(home / 'fakebin') + ':' + BASE['PATH']}

    def run(command, identity=OWNER, payload=None, thread_identity=None):
        call_env = env.copy()
        if identity is not None:
            call_env |= {'CODEX_SESSION_ID': identity,
                         'CODEX_THREAD_ID': identity if thread_identity is None else thread_identity}
        return subprocess.run(['bash', '-c', command], input=payload,
                              env=call_env, text=True, capture_output=True,
                              timeout=30)

    if '--live' in sys.argv:
        # The installed server generates both sessions and their hook payloads.
        # An isolated provider points at a closed loopback port. No credentials
        # or model requests leave the fixture, and model success is not a gate.
        codex_home = home / 'codex-home'
        codex_home.mkdir()
        (codex_home / 'config.toml').write_text(
            'model_provider="fixture"\nmodel="fixture"\n'
            '[features]\nhooks=true\n'
            '[model_providers.fixture]\nname="fixture"\n'
            'base_url="http://127.0.0.1:1/v1"\nwire_api="responses"\n'
            'requires_openai_auth=false\nrequest_max_retries=0\nstream_max_retries=0\n')
        capture = home / 'capture.sh'
        capture.write_text('#!/usr/bin/env bash\npayload=$(cat)\nid=$(printf \'%s\' "$payload" | jq -er \'.session_id\') || exit 1\nprintf \'%s\' "$payload" | "$FM_HOME/bin/fm-sessionstart-run.sh" > "$FM_HOME/state/$id.startup"\nprintf \'%s\\n\' "$id" >> "$FM_HOME/state/observed-sessions"\n')
        capture.write_text(capture.read_text().replace('printf \'%s\\n\' \"$id\" >>', 'printf \'%s\' \"$payload\" | python3 ~/.no-mistakes/evidence/01M6RF5MKEHX33BP21ENCYD6C0/native-hook-probe.py\nprintf \'%s\\n\' \"$id\" >>'))
        capture.chmod(0o755)
        (codex_home / 'hooks.json').write_text(json.dumps({'hooks': {
            'SessionStart': [{'hooks': [{'type': 'command',
                                        'command': str(capture), 'timeout': 180}]}]}}))
        live_env = env | {'CODEX_HOME': str(codex_home), 'PATH': BASE['PATH']}
        logfile=pathlib.Path('~/.no-mistakes/evidence/01M6RF5MKEHX33BP21ENCYD6C0/cli-process.log').open('w')
        process=subprocess.Popen([shutil.which('codex'), 'exec', '--skip-git-repo-check', '--ephemeral', '--sandbox', 'danger-full-access', 'Isolated CLI ownership check.'],cwd=home,env=live_env|{'FM_VALIDATION_CLI':'1'},stdout=logfile,stderr=logfile,start_new_session=True)
        try:
            observed=home/'state/observed-sessions'
            for _ in range(450):
                if observed.exists() or process.poll() is not None: break
                time.sleep(.1)
            assert observed.exists(), 'CLI did not emit SessionStart, see cli-process.log'
            identity=observed.read_text().splitlines()[0]
            rows=json.loads((home/('state/'+identity+'.probe.json')).read_text())
            for row in rows: print(json.dumps(row),flush=True)
            assert all(row['pass_'] for row in rows), rows
            assert not (home/'state/.lock-session').exists(), 'ordinary CLI created native sidecar'
            print('Ordinary CLI retained PID ownership.')
        finally:
            if process.poll() is None: os.killpg(process.pid,signal.SIGTERM)
            print('CLI process exit:',process.wait(timeout=10))
            logfile.close()
            dest=pathlib.Path('~/.no-mistakes/evidence/01M6RF5MKEHX33BP21ENCYD6C0/cli-state')
            dest.mkdir(exist_ok=True)
            for file in (home/'state').iterdir():
                if file.is_file(): shutil.copy(file,dest/file.name)
