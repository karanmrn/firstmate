from pathlib import Path
root=Path.cwd()
out=Path('~/.no-mistakes/evidence/01M6RYVFH7BH12KJMDCASDZAXK')
s=(root/'tests/fm-codex-session-lock-repro.py').read_text()
s=s.replace('REPO = pathlib.Path(__file__).resolve().parent.parent','REPO = pathlib.Path('+repr(str(root))+')')
s=s.replace("[shutil.which('codex'), 'app-server', '--listen', 'stdio://']", "[shutil.which('codex')] + json.loads(os.environ['NATIVE_LAUNCH_JSON'])")
start=s.index('        capture.write_text(')
end=s.index('        capture.chmod',start)
hook='''#!/usr/bin/env bash
payload=$(cat)
id=$(printf '%s' "$payload" | jq -er '.session_id') || exit 1
env -u CODEX_SESSION_ID -u CODEX_THREAD_ID -u FM_CODEX_HOOK_SESSION_ID "$FM_HOME/bin/fm-lock.sh" > "$FM_HOME/state/$id.unidentified" 2>&1
printf '%s\\n' "$?" > "$FM_HOME/state/$id.unidentified-status"
printf '%s' "$payload" | "$FM_HOME/bin/fm-sessionstart-run.sh" > "$FM_HOME/state/$id.startup"
printf '%s\\n' "$id" >> "$FM_HOME/state/observed-sessions"
'''
s=s[:start]+'        capture.write_text('+repr(hook)+')\n'+s[end:]
start=s.index("            assert identities[0] != identities[1]")
end=s.index('        finally:',start)
checks='''            assert identities[0] != identities[1]
            record={'launch':json.loads(os.environ['NATIVE_LAUNCH_JSON']), 'server_pid':process.pid, 'sessions':[]}
            for index,sid in enumerate(identities):
                startup=(home/('state/'+sid+'.startup')).read_text()
                unidentified=(home/('state/'+sid+'.unidentified')).read_text()
                status=(home/('state/'+sid+'.unidentified-status')).read_text().strip()
                record['sessions'].append({'id':sid,'startup':startup,'unidentified':unidentified,'unidentified_status':status})
                assert status=='1',record
                if os.environ['ARG_CASE']=='ambiguous':
                    assert 'READ-ONLY SESSION' in startup,record
                else:
                    assert ('lock acquired:' if index==0 else 'READ-ONLY SESSION') in startup,record
            if os.environ['ARG_CASE']=='ambiguous':
                assert not (home/'state/.lock').exists()
                assert not (home/'state/.lock-session').exists()
            pathlib.Path(os.environ['ARG_EVIDENCE']).write_text(json.dumps(record,indent=2))
            print('ok - real '+os.environ['ARG_CASE']+' app-server launch: unidentified acquisition refused; hook identity boundary preserved')
'''
s=s[:start]+checks+s[end:]
(out/'native-argument-driver.py').write_text(s)
