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
    stderr=(evidence/'native-server.stderr').open('w')
    proc=subprocess.Popen(['codex','app-server','--listen','stdio://'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr,env=env,start_new_session=True)
    buffer=bytearray()
    def request(n,method,params):
        proc.stdin.write((json.dumps(dict(id=n,method=method,params=params))+'\n').encode());proc.stdin.flush()
        end=time.monotonic()+30
        while time.monotonic()<end:
            while b'\n' in buffer:
                line,_,rest=buffer.partition(b'\n');buffer[:]=rest
                item=json.loads(line)
                if item.get('id')==n:
                    assert 'error' not in item,item
                    return item['result']
            ready=select.select([proc.stdout],[],[],max(0,end-time.monotonic()))[0]
            assert ready,'app-server timeout'
            chunk=os.read(proc.stdout.fileno(),65536);assert chunk,'app-server exited'
            buffer.extend(chunk)
        raise AssertionError('app-server timeout')
    try:
        version=request(1,'initialize',{'clientInfo':{'name':'fm-live-probe','version':'1'},'capabilities':{'experimentalApi':True}})['userAgent']
        print('Installed product:',version,flush=True)
        proc.stdin.write(b'{"method":"initialized"}\n');proc.stdin.flush()
        identities=[]
        for n in (2,4):
            thread=request(n,'thread/start',dict(cwd=str(home),approvalPolicy='never',sandbox='danger-full-access',config={'bypass_hook_trust':True}))['thread']
            sid=thread['sessionId'];identities.append(sid)
            request(n+1,'turn/start',dict(threadId=thread['id'],input=[dict(type='text',text='Isolated native hook boundary probe.')]))
            deadline=time.monotonic()+150
            done=home/('state/'+sid+'.probe-done')
            while not done.exists() and time.monotonic()<deadline:time.sleep(.1)
            assert done.exists(),'native probe hook did not finish'
            assert done.read_text()=='pass',(evidence/('owner-probe.json' if n==2 else 'competitor-probe.json')).read_text()
            print('Native session',sid,'probe passed',flush=True)
        assert identities[0]!=identities[1]
        print('Both native sessions preserved one owner. No process-table substitution was used.',flush=True)
    finally:
        os.killpg(proc.pid,signal.SIGTERM)
        print('Native server terminated with exit',proc.wait(timeout=15),flush=True)
        stderr.close()

    for name in ('.lock','.lock-session','task.meta'):
        (home/'state'/name).unlink(missing_ok=True)
    (codex_home/'hooks.json').write_text(json.dumps({'hooks':{'SessionStart':[{'hooks':[{'type':'command','command':'python3 '+str(evidence/'cli-hook-probe.py'),'timeout':90}]}]}}))
    with (evidence/'cli-provider.log').open('w') as log:
        cli=subprocess.run(['codex','exec','--skip-git-repo-check','--sandbox','read-only','Isolated CLI SessionStart probe.'],cwd=home,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=100)
    print('CLI exited after the closed loopback provider response:',cli.returncode,flush=True)
    result=json.loads((evidence/'cli-probe.json').read_text())
    assert result['result']=='pass',result
    print('Real Codex CLI startup, lock reentry, and ownership passed without a native sidecar.',flush=True)
