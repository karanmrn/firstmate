import json, os, pathlib, subprocess, sys
home=pathlib.Path(os.environ['FM_HOME']);raw=sys.stdin.read();payload=json.loads(raw)
records=[]
try:
    for name,command,expected in [
        ('ordinary CLI SessionStart','"$FM_HOME/bin/fm-sessionstart-run.sh"','lock acquired:'),
        ('ordinary CLI reentry','"$FM_HOME/bin/fm-lock.sh"','lock acquired:'),
        ('ordinary CLI ownership','. "$FM_HOME/bin/fm-session-lock-lib.sh"; fm_session_lock_owned_by_self "$FM_HOME/state"',None)]:
        p=subprocess.run(['bash','-c',command],input=raw,env=os.environ,text=True,capture_output=True,timeout=30)
        records.append(dict(name=name,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr))
        assert p.returncode==0,(name,p.stdout,p.stderr)
        if expected:assert expected in p.stdout+p.stderr,(name,p.stdout,p.stderr)
    assert not (home/'state/.lock-session').exists(),'CLI fabricated a native identity sidecar'
    result=dict(result='pass',session_id=payload['session_id'],lock_pid=(home/'state/.lock').read_text().strip(),checks=records)
except BaseException as e:
    result=dict(result='fail',checks=records,error=repr(e))
pathlib.Path(os.environ['PROBE_EVIDENCE'],'cli-probe.json').write_text(json.dumps(result,indent=2))
