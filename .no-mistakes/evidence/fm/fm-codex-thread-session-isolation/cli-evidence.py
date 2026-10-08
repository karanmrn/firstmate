import os, pathlib, tempfile, subprocess, shutil, json, signal, time
repo=pathlib.Path.cwd()
evidence=pathlib.Path('/Users/karanmanoharan/.no-mistakes/evidence/01M4DEY2V71QRR9X00H9DCKW4R')
base={k:v for k,v in os.environ.items() if not k.startswith(('FM_', 'CODEX_', 'CLAUDE_', 'HERDR_', 'TASKS_AXI_', 'CURSOR_', 'PI_'))}
with tempfile.TemporaryDirectory(prefix='fm-cli-live-') as temp:
    root=pathlib.Path(temp)
    for harness in ('codex', 'claude'):
        home=root/harness
        home.mkdir()
        subprocess.run([str(repo/'bin/fm-lab-home.sh'), 'create', str(home)], env=base, check=True, capture_output=True)
        capture=home/'capture.sh'
        capture.write_text('''#!/usr/bin/env bash
cat > "$FM_HOME/payload.json"
{
  "$FM_CODE_ROOT/bin/fm-lock.sh"
  printf 'initial lock exit=%s\\n' "$?"
  "$FM_CODE_ROOT/bin/fm-lock.sh"
  printf 'reentry exit=%s\\n' "$?"
  . "$FM_CODE_ROOT/bin/fm-session-lock-lib.sh"
  fm_session_lock_owned_by_self "$FM_HOME/state"
  printf 'owner proof exit=%s\\n' "$?"
  printf 'anchor pid: '; cat "$FM_HOME/state/.lock"
  printf 'sidecar: '; cat "$FM_HOME/state/.lock-session" 2>/dev/null || true
} > "$FM_HOME/actions.log" 2>&1
touch "$FM_HOME/complete"
''')
        capture.chmod(0o755)
        hook={'hooks':{'SessionStart':[{'hooks':[{'type':'command','command':str(capture),'timeout':30}]}]}}
        env=base|{'FM_HOME':str(home),'FM_CODE_ROOT':str(repo)}
        if harness=='codex':
            config=home/'codex-home'
            config.mkdir()
            (config/'config.toml').write_text('model_provider="fixture"\nmodel="fixture"\n[features]\nhooks=true\n[model_providers.fixture]\nname="fixture"\nbase_url="http://127.0.0.1:1/v1"\nwire_api="responses"\nrequires_openai_auth=false\nrequest_max_retries=0\nstream_max_retries=0\n')
            (config/'hooks.json').write_text(json.dumps(hook))
            env['CODEX_HOME']=str(config)
            command=['codex','exec','--dangerously-bypass-hook-trust','--skip-git-repo-check','-C',str(home),'Token-free hook validation.']
        else:
            settings=home/'settings.json'
            settings.write_text(json.dumps(hook))
            env|={'ANTHROPIC_BASE_URL':'http://127.0.0.1:1','CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC':'1'}
            command=['claude','-p','--no-session-persistence','--setting-sources','','--settings',str(settings),'Token-free hook validation.']
        with (evidence/(harness+'-cli-process.log')).open('w') as log:
            proc=subprocess.Popen(command, cwd=home, env=env, stdout=log, stderr=log, start_new_session=True)
            try:
                end=time.monotonic()+45
                while time.monotonic()<end and not (home/'complete').exists() and proc.poll() is None:
                    time.sleep(.1)
                if not (home/'complete').exists():
                    print(harness, 'SessionStart hook unavailable. exit=',proc.poll(),flush=True)
                    continue
                actions=(home/'actions.log').read_text()
                shutil.copy(home/'actions.log',evidence/(harness+'-cli-actions.log'))
                shutil.copy(home/'payload.json',evidence/(harness+'-cli-payload.json'))
                print(harness+' real CLI hook:\n'+actions,flush=True)
                for expected in ('initial lock exit=0','reentry exit=0','owner proof exit=0'):
                    assert expected in actions, actions
                assert not (home/'state/.lock-session').exists() or not (home/'state/.lock-session').read_text().startswith('codex-native:'), 'ordinary CLI got native sidecar'
            finally:
                if proc.poll() is None:
                    os.killpg(proc.pid,signal.SIGTERM)
                proc.wait(timeout=15)
