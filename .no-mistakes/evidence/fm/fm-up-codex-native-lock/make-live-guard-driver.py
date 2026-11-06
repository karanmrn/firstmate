from pathlib import Path
root = Path.cwd()
evidence = Path('~/.no-mistakes/evidence/01M6RYVFH7BH12KJMDCASDZAXK')
source = (root / 'tests/fm-codex-session-lock-repro.py').read_text()
source = source.replace('REPO = pathlib.Path(__file__).resolve().parent.parent', 'REPO = pathlib.Path(' + repr(str(root)) + ')')
start = source.index('        capture.write_text(')
end = source.index('        capture.chmod', start)
hook = '''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
h=pathlib.Path(os.environ['FM_HOME'])
payload=sys.stdin.read()
sid=json.loads(payload)['session_id']
records=[]
def call(label, args, data=None, identity=True, extra=None):
    env=os.environ.copy()
    for k in ('CODEX_SESSION_ID','CODEX_THREAD_ID','FM_CODEX_HOOK_SESSION_ID'):
        env.pop(k,None)
    if identity:
        env.update(CODEX_SESSION_ID=sid,CODEX_THREAD_ID=sid)
    if extra: env.update(extra)
    p=subprocess.run(args,input=data,env=env,text=True,capture_output=True,timeout=30)
    records.append(dict(label=label,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr))
    return p
first=not (h/'state/.lock').exists()
if first:
    p=call('native server without identity refuses empty home',[str(h/'bin/fm-lock.sh')],identity=False)
    assert p.returncode==1 and not (h/'state/.lock').exists(), records
p=call('native SessionStart', [str(h/'bin/fm-sessionstart-run.sh')],payload,False)
(h/('state/'+sid+'.startup')).write_text(p.stdout)
owner=(h/'state/.lock-session').read_text().strip()=='codex-native:'+sid
before=[(h/'state'/f).read_bytes() for f in ('.lock','.lock-session')]
p=call('same-thread reentry' if owner else 'foreign thread acquisition', [str(h/'bin/fm-lock.sh')])
assert p.returncode==(0 if owner else 1), records
p=call('identity ownership verdict',['bash','-c','. "$FM_HOME/bin/fm-session-lock-lib.sh"; fm_session_lock_owned_by_self "$FM_HOME/state"'])
assert p.returncode==(0 if owner else 1),records
p=call('mismatched descendant identity is refused',[str(h/'bin/fm-lock.sh')],extra={'CODEX_THREAD_ID':'00000000-0000-4000-8000-999999999999'})
assert p.returncode==1,records
p=call('real bounded checkpoint',[str(h/'bin/fm-watch-checkpoint.sh'),'--seconds','1'])
assert p.returncode==(124 if owner else 1),records
if owner: assert 'checkpoint: no actionable wake within 1s' in p.stdout, records
else: assert 'operate read-only' in p.stderr, records
(h/'state/task.meta').write_text('project=fixture\\n')
stop=json.dumps({'session_id':sid,'stop_hook_active':False})
if not owner:
    p=call('foreign direct Stop is read-only',[str(h/'bin/fm-turnend-guard.sh')],stop,False)
    assert p.returncode==0 and 'OWNED BY ANOTHER LIVE SESSION' in p.stdout, records
for opted in (False,True):
    if opted: (h/'config/codex-stop-park').touch()
    (h/'state/.codex-park-fallback').write_text(sid+'\\n')
    p=call('retained fallback Stop, park opt-in='+str(opted),[str(h/'bin/fm-codex-stop-park.sh'),'--guard'],stop,False)
    assert p.returncode==(2 if owner else 0),records
    if owner: assert 'foreground fallback' in p.stderr,records
    else: assert 'OWNED BY ANOTHER LIVE SESSION' in p.stdout,records
    assert (h/'state/.codex-park-fallback').read_text()==sid+'\\n',records
(h/'state/.codex-park-fallback').unlink()
(h/'config/codex-stop-park').unlink(missing_ok=True)
(h/'state/task.meta').unlink()
bad=json.dumps({'session_id':'invalid','source':'startup'})
p=call('malformed hook cannot borrow environment',[str(h/'bin/fm-sessionstart-run.sh')],bad)
assert 'READ-ONLY SESSION' in p.stdout,records
assert [(h/'state'/f).read_bytes() for f in ('.lock','.lock-session')]==before,records
out=pathlib.Path(os.environ['LIVE_GUARD_EVIDENCE'])
(out/(sid+'.json')).write_text(json.dumps({'session_id':sid,'owner':owner,'lock_pid':before[0].decode().strip(),'lock_identity':before[1].decode().strip(),'results':records},indent=2))
with (h/'state/observed-sessions').open('a') as f: f.write(sid+'\\n')
'''
hook=hook.replace('records=[]', "records=[]\ndef failed(t,v,b):\n    pathlib.Path(os.environ['LIVE_GUARD_EVIDENCE'],'hook-error.json').write_text(json.dumps({'error':str(v),'results':records},indent=2))\n    sys.__excepthook__(t,v,b)\nsys.excepthook=failed")
hook=hook.replace('timeout=30','timeout=90')
source=source.replace("str(capture), 'timeout': 30", "str(capture), 'timeout': 300")
source=source.replace('range(300)', 'range(2400)')
source=source[:start] + '        capture.write_text(' + repr(hook) + ')\n' + source[end:]
source=source.replace("live_env = env | {'CODEX_HOME': str(codex_home), 'PATH': BASE['PATH']}", "shutil.copy(REPO / 'bin/fm-watch.sh', home / 'bin/fm-watch.sh')\n        live_env = env | {'CODEX_HOME': str(codex_home), 'PATH': BASE['PATH'], 'LIVE_GUARD_EVIDENCE': " + repr(str(evidence)) + "}")
source=source.replace("range(300)","range(600)")
source=source.replace("time.sleep(0.1)\n                else:","time.sleep(0.1)\n                else:")
source=source.replace("assert identities[0] != identities[1]", "print('real native sessions:', identities, 'server PID:', process.pid, flush=True)\n            assert identities[0] != identities[1]")
(evidence/'live-guard-driver.py').write_text(source)
