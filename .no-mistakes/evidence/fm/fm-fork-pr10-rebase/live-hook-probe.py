import json, os, pathlib, subprocess, sys
home=pathlib.Path(os.environ['FM_HOME'])
raw=sys.stdin.read()
payload=json.loads(raw)
sid=payload['session_id']
owner_path=home/'state/probe-owner'
owner=owner_path.read_text().strip() if owner_path.exists() else sid
phase='owner' if sid==owner else 'competitor'
records=[]
def run(name,command,rc,contains=None,identity=None,thread=None,data=None):
    env=os.environ.copy()
    for key in ('CODEX_SESSION_ID','CODEX_THREAD_ID','FM_CODEX_HOOK_SESSION_ID'):
        env.pop(key,None)
    if identity is not None: env['CODEX_SESSION_ID']=identity
    if thread is not None: env['CODEX_THREAD_ID']=thread
    p=subprocess.run(['bash','-c',command],input=data,env=env,text=True,capture_output=True,timeout=30)
    records.append(dict(name=name,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr))
    assert p.returncode==rc, (name,p.returncode,p.stdout,p.stderr)
    if contains is not None: assert contains in p.stdout+p.stderr, (name,p.stdout,p.stderr)
    return p
start='"$FM_HOME/bin/fm-sessionstart-run.sh"'
lock='"$FM_HOME/bin/fm-lock.sh"'
own='. "$FM_HOME/bin/fm-session-lock-lib.sh"; fm_session_lock_owned_by_self "$FM_HOME/state"'
checkpoint='"$FM_HOME/bin/fm-watch-checkpoint.sh" --seconds 1'
stop='"$FM_HOME/bin/fm-codex-stop-park.sh" --guard'
try:
    if phase=='owner':
        owner_path.write_text(sid)
        run('native SessionStart owner acquires',start,0,'lock acquired:',data=raw)
        before=(home/'state/.lock').read_bytes()
        sidecar=(home/'state/.lock-session').read_bytes()
        assert sidecar.decode().strip()=='codex-native:'+sid
        run('same native owner reenters',lock,0,identity=sid,thread=sid)
        run('same native owner proves ownership',own,0,identity=sid,thread=sid)
        p=run('resume owner hook suppresses nudge',start,0,data=json.dumps(dict(source='resume',session_id=sid)))
        assert p.stdout=='',p.stdout
        run('missing payload identity refuses retained environment',start,0,'READ-ONLY SESSION',identity=sid,thread=sid,data='{"source":"startup"}')
        run('invalid native identity is refused',lock,1,identity='invalid')
        run('missing native identity is refused',lock,1)
        # A descendant inherits its root session ID but has its own thread ID.
        foreign='00000000-0000-4000-8000-000000000002'
        run('descendant ownership is refused',own,1,identity=sid,thread=foreign)
        run('descendant lock acquisition is refused',lock,1,identity=sid,thread=foreign)
        run('descendant startup is read-only',start,0,'READ-ONLY SESSION',identity=sid,thread=foreign,data=raw)
        run('descendant checkpoint is refused',checkpoint,1,'does not own the home lock',identity=sid,thread=foreign)
        (home/'state/task.meta').write_text('project=probe\n')
        run('descendant Stop permits read-only exit',stop,0,'OWNED BY ANOTHER LIVE SESSION',identity=sid,thread=foreign,data=json.dumps(dict(session_id=sid,stop_hook_active=False)))
        (home/'state/task.meta').unlink()
        (home/'state/.lock-session').unlink()
        run('legacy PID-only native lock is refused',lock,1,identity=sid,thread=sid)
        assert not (home/'state/.lock-session').exists()
        run('legacy PID-only checkpoint is refused',checkpoint,1,'does not own the home lock',identity=sid,thread=sid)
        (home/'state/.lock-session').write_bytes(sidecar)
        run('native owner runs a real bounded watcher',checkpoint,124,'checkpoint: no actionable wake within 1s',identity=sid,thread=sid)
        assert not (home/'state/.watch.lock/pid').exists()
        assert (home/'state/.lock').read_bytes()==before
        assert (home/'state/.lock-session').read_bytes()==sidecar
    else:
        before=(home/'state/.lock').read_bytes()
        sidecar=(home/'state/.lock-session').read_bytes()
        run('second native SessionStart is read-only',start,0,'READ-ONLY SESSION',data=raw)
        run('second native session cannot acquire',lock,1,identity=sid,thread=sid)
        run('second native session cannot prove ownership',own,1,identity=sid,thread=sid)
        run('second native resume receives startup nudge',start,0,'FIRSTMATE_OP:',data=json.dumps(dict(source='resume',session_id=sid)))
        run('contradictory native hook is read-only',start,0,'READ-ONLY SESSION',identity=owner,thread=owner,data=raw)
        run('second native checkpoint is refused',checkpoint,1,'does not own the home lock',identity=sid,thread=sid)
        (home/'state/task.meta').write_text('project=probe\n')
        run('second native Stop permits read-only exit',stop,0,'OWNED BY ANOTHER LIVE SESSION',data=json.dumps(dict(session_id=sid,stop_hook_active=False)))
        assert (home/'state/.lock').read_bytes()==before
        assert (home/'state/.lock-session').read_bytes()==sidecar
    result=dict(phase=phase,session_id=sid,lock_pid=(home/'state/.lock').read_text().strip(),sidecar=(home/'state/.lock-session').read_text().strip(),checks=records,result='pass')
except BaseException as e:
    result=dict(phase=phase,session_id=sid,checks=records,result='fail',error=repr(e))
finally:
    evidence=pathlib.Path(os.environ['PROBE_EVIDENCE'])
    (evidence/(phase+'-probe.json')).write_text(json.dumps(result,indent=2))
    (home/('state/'+sid+'.probe-done')).write_text(result['result'])
