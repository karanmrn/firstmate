import json, os, pathlib, select, shutil, signal, subprocess, tempfile, time
repo=pathlib.Path.cwd()
evidence=pathlib.Path('~/.no-mistakes/evidence/01M6RF5MKEHX33BP21ENCYD6C0')
base={k:v for k,v in os.environ.items() if not k.startswith(('FM_','CODEX_','CLAUDE_','HERDR_','TASKS_AXI_','CURSOR_','PI_','GIT_','NO_MISTAKES_'))}
base.update(GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_NOSYSTEM='1')
with tempfile.TemporaryDirectory(prefix='native-live-',dir=repo/'.gate-test-tmp') as tmp:
    home=pathlib.Path(tmp)
    subprocess.run(['bash','bin/fm-lab-home.sh','create',str(home)],check=True,env=base)
    shutil.copytree(repo/'bin',home/'bin')
    shutil.copy(repo/'AGENTS.md',home/'AGENTS.md')
    subprocess.run(['git','init','-q',str(home)],check=True,env=base)
    # External fleet/network leaves stay inert. All lock, hook, guard,
    # checkpoint, and watcher executables are the unchanged target product.
    for name in ('fm-bootstrap.sh','fm-herdr-session-cleanup.sh','fm-startup-network.sh','fm-home-summary-refresh.sh','fm-guard.sh','fm-lease.sh','fm-branch-outcome.sh','fm-public-followup.sh'):
        (home/'bin'/name).write_text('#!/usr/bin/env bash\nexit 0\n')
    codex_home=home/'codex-home';codex_home.mkdir()
    (codex_home/'config.toml').write_text('model_provider="fixture"\nmodel="fixture"\n[features]\nhooks=true\n[model_providers.fixture]\nname="fixture"\nbase_url="http://127.0.0.1:1/v1"\nwire_api="responses"\nrequires_openai_auth=false\nrequest_max_retries=0\nstream_max_retries=0\n')
    (codex_home/'hooks.json').write_text(json.dumps({'hooks':{'SessionStart':[{'hooks':[{'type':'command','command':'python3 '+str(evidence/'live-hook-probe.py'),'timeout':180}]}]}}))
    env=base|dict(FM_HOME=str(home),FM_ROOT_OVERRIDE=str(home),CODEX_HOME=str(codex_home),PROBE_EVIDENCE=str(evidence),FM_POLL='1',FM_SIGNAL_GRACE='1',FM_CHECK_INTERVAL='999999')
    for name in ('.lock','.lock-session','task.meta'):
        (home/'state'/name).unlink(missing_ok=True)
    (codex_home/'hooks.json').write_text(json.dumps({'hooks':{'SessionStart':[{'hooks':[{'type':'command','command':'python3 '+str(evidence/'cli-hook-probe.py'),'timeout':90}]}]}}))
    result_path=evidence/'cli-probe.json'
    result_path.unlink(missing_ok=True)
    with (evidence/'cli-provider.log').open('w') as log:
        cli=subprocess.Popen(['codex','exec','--dangerously-bypass-hook-trust','--skip-git-repo-check','--sandbox','read-only','Isolated CLI SessionStart probe.'],cwd=home,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            deadline=time.monotonic()+60
            while not result_path.exists() and time.monotonic()<deadline and cli.poll() is None:
                time.sleep(.1)
            assert result_path.exists(),'CLI SessionStart hook did not finish'
            result=json.loads(result_path.read_text())
            assert result['result']=='pass',result
            print('Real Codex CLI startup, lock reentry, and ownership passed without a native sidecar.',flush=True)
        finally:
            if cli.poll() is None:os.killpg(cli.pid,signal.SIGTERM)
            print('Stopped the disposable CLI after the hook probe. Exit status:',cli.wait(timeout=15),flush=True)
