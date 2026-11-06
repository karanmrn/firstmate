import os,sys,json,subprocess,pathlib
payload=sys.stdin.read()
sid=json.loads(payload)['session_id']
home=pathlib.Path(os.environ['FM_HOME'])
state=pathlib.Path(os.environ.get('FM_STATE_OVERRIDE',str(home/'state')))
cli=os.environ.get('FM_VALIDATION_CLI')=='1'
observed=state/'observed-sessions'
owner=observed.read_text().splitlines()[0] if observed.exists() else sid
results=[]
base={k:v for k,v in os.environ.items() if k not in ['CODEX_SESSION_ID','CODEX_THREAD_ID','FM_CODEX_HOOK_SESSION_ID']}
def call(name,cmd,env=None,data=None,expect=None,contains=None,absent=None):
    proc=subprocess.run(['bash','-c',cmd],env=base|(env or {}),input=data,text=True,capture_output=True,timeout=35)
    good=(expect is None or proc.returncode==expect) and (contains is None or contains in proc.stdout+proc.stderr) and (absent is None or absent not in proc.stdout+proc.stderr)
    row=dict(name=name,exit=proc.returncode,stdout=proc.stdout,stderr=proc.stderr,pass_=good)
    results.append(row)
    (state/(sid+'.probe.json')).write_text(json.dumps(results,indent=2))
    return proc
lock='"$FM_HOME/bin/fm-lock.sh"'
start='"$FM_HOME/bin/fm-sessionstart-run.sh"'
owned='. "$FM_HOME/bin/fm-session-lock-lib.sh"; fm_session_lock_owned_by_self "${FM_STATE_OVERRIDE:-$FM_HOME/state}"'
checkpoint='"$FM_HOME/bin/fm-watch-checkpoint.sh" --seconds 1'
ids={'CODEX_SESSION_ID':sid,'CODEX_THREAD_ID':sid}
if cli:
    call('Ordinary CLI acquires without native identity',lock,expect=0,contains='lock acquired:')
    call('Ordinary CLI reenters without native identity',lock,expect=0)
    call('Ordinary CLI proves PID ownership',owned,expect=0)
    print(json.dumps(results))
    (state/"cli-tool.complete").write_text("complete\n")
    sys.exit(0)
before=(state/'.lock').read_bytes()
sidecar=(state/'.lock-session').read_bytes()
if owner==sid:
    call('Native owner reenters',lock,ids,expect=0)
    call('Native owner proves ownership',owned,ids,expect=0)
    call('Resume hook preserves owner without tool identity',start,data=json.dumps({'session_id':sid,'source':'resume'}),expect=0,absent='Run `bin/fm-session-start.sh`')
    call('Compact hook preserves owner without tool identity',start,data=json.dumps({'session_id':sid,'source':'compact'}),expect=0,absent='READ-ONLY SESSION')
    call('Missing identity cannot use shared PID',lock,expect=1,contains='no trusted session identity')
    call('Malformed identity cannot use shared PID',lock,{'CODEX_SESSION_ID':'invalid'},expect=1)
    call('Owner runs the real bounded watcher',checkpoint,ids|{'FM_POLL':'1','FM_CHECK_INTERVAL':'999999','FM_SIGNAL_GRACE':'1'},expect=124,contains='no actionable wake within 1s')
else:
    call('Competing real thread cannot acquire',lock,ids,expect=1,contains='another live firstmate session holds the lock')
    call('Competing real thread cannot prove ownership',owned,ids,expect=1)
    call('Root identity with conflicting current thread cannot acquire',lock,{'CODEX_SESSION_ID':owner,'CODEX_THREAD_ID':sid},expect=1)
    call('Root identity with conflicting current thread cannot prove ownership',owned,{'CODEX_SESSION_ID':owner,'CODEX_THREAD_ID':sid},expect=1)
    beat=(state/'.last-watcher-beat').read_bytes() if (state/'.last-watcher-beat').exists() else None
    call('Competing thread cannot start checkpoint',checkpoint,ids,expect=1,contains='does not own the home lock')
    call('Conflicting descendant identity cannot start checkpoint',checkpoint,{'CODEX_SESSION_ID':owner,'CODEX_THREAD_ID':sid},expect=1,contains='does not own the home lock')
    results.append(dict(name='Refused checkpoints do not start a watcher',pass_=not (state/'.watch.lock/pid').exists() and beat==((state/'.last-watcher-beat').read_bytes() if (state/'.last-watcher-beat').exists() else None)))
    (state/'task.meta').write_text('project=fixture\n')
    stop='"$FM_HOME/bin/fm-turnend-guard.sh"'
    call('Foreign Stop exits with read-only diagnostic',stop,data=json.dumps({'session_id':sid,'stop_hook_active':False}),expect=0,contains='OWNED BY ANOTHER LIVE SESSION')
    call('Conflicting descendant Stop exits with read-only diagnostic',stop,{'CODEX_SESSION_ID':owner,'CODEX_THREAD_ID':sid},data=json.dumps({'session_id':owner,'stop_hook_active':False}),expect=0,contains='OWNED BY ANOTHER LIVE SESSION')
    (state/'task.meta').unlink()
    call('Contradictory hook identity stays read-only',start,{'CODEX_SESSION_ID':owner,'CODEX_THREAD_ID':owner},data=json.dumps({'session_id':sid,'source':'startup'}),expect=0,contains='READ-ONLY SESSION')
    call('Missing hook identity cannot use retained environment',start,{'CODEX_SESSION_ID':owner,'CODEX_THREAD_ID':owner},data=json.dumps({'source':'startup'}),expect=0,contains='READ-ONLY SESSION')
    call('Resume nudges foreign thread',start,data=json.dumps({'session_id':sid,'source':'resume'}),expect=0,contains='Run `bin/fm-session-start.sh`')
    call('Compact cannot reacquire foreign lock',start,data=json.dumps({'session_id':sid,'source':'compact'}),expect=0,contains='READ-ONLY SESSION')
    (state/'.lock-session').unlink()
    call('Legacy native PID-only lock stays read-only',lock,ids,expect=1)
    results.append(dict(name='Legacy check does not invent sidecar',pass_=not (state/'.lock-session').exists()))
    (state/'.lock-session').write_bytes(sidecar)
    (state/'owner-pid').write_bytes(before)
    (state/'.lock').unlink()
    (state/'.lock').symlink_to(state/'owner-pid')
    call('Symlink lock cannot prove native ownership',owned,{'CODEX_SESSION_ID':owner,'CODEX_THREAD_ID':owner},expect=1)
    call('Symlink lock cannot be acquired',lock,ids,expect=1)
    (state/'.lock').unlink()
    (state/'.lock').write_bytes(before)
results.append(dict(name='Adversarial attempts preserve original lock and sidecar',pass_=(state/'.lock').read_bytes()==before and (state/'.lock-session').read_bytes()==sidecar))
(state/(sid+'.probe.json')).write_text(json.dumps(results,indent=2))
