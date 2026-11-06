import json,pathlib,subprocess,shutil,stat
root=pathlib.Path.cwd()
out=pathlib.Path('~/.no-mistakes/evidence/01M6RYVFH7BH12KJMDCASDZAXK')
native=[json.loads(f.read_text()) for f in sorted(out.glob('01a*.json'))]
assert len(native)==2 and sum(x['owner'] for x in native)==1
pids={int(x['lock_pid']) for x in native}
for name in ('plain-cli','crewmate-cli','secondmate-cli','embedded-cli','embedded-cli-with-id'):
 d=json.loads((out/(name+'-result.json')).read_text())
 assert d['returncode']==0 and d['identity'] is None
 pids.add(int(d['lock']))
for name in ('balanced','ambiguous'):
 d=json.loads((out/(name+'-arguments.json')).read_text())
 assert all(x['unidentified_status']=='1' for x in d['sessions'])
 if name=='ambiguous': assert all('READ-ONLY SESSION' in x['startup'] for x in d['sessions'])
baseline=json.loads((out/'base-reproduction.json').read_text())
assert all('lock acquired:' in x['startup'] for x in baseline['sessions'])
pids.add(baseline['server_pid'])
assert 'ALL PASS' in (out/'portable-lock.log').read_text()
assert 'ALL PASS' in (out/'native-hook.log').read_text()
checks=[]
for pid in sorted(pids):
 p=subprocess.run(['ps','-o','comm=','-p',str(pid)],text=True,capture_output=True)
 checks.append({'pid':pid,'ps_exit':p.returncode,'comm':p.stdout.strip()})
 assert p.returncode==1 and not p.stdout.strip(), checks
socket=root/'.s'
if socket.exists():
 p=subprocess.run(['tmux','-S',str(socket),'list-sessions'],text=True,capture_output=True)
 assert p.returncode==1 and 'no server running' in p.stderr,p.stderr
 assert stat.S_ISSOCK(socket.lstat().st_mode)
 socket.unlink()
shutil.rmtree(root/'.test-tmp')
(out/'cleanup.json').write_text(json.dumps({'owned_process_checks':checks,'private_tmux_socket_absent':not socket.exists(),'workspace_fixture_removed':not (root/'.test-tmp').exists()},indent=2))
print('Retained product results verified. All recorded server and TUI PIDs exited. Disposable workspace fixtures removed.')
