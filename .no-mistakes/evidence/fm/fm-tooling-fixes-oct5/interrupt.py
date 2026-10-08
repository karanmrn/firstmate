import os, subprocess, time, signal, json
from pathlib import Path
root=Path.cwd()
ev=Path('/Users/karanmanoharan/.no-mistakes/evidence/01M4DR9JRJQ9KWVJ2ZGHKNTQNR')
base=subprocess.run(['git','show','67f351c:tests/fm-watcher-lock.test.sh'],capture_output=True,text=True,check=True).stdout
current=(root/'tests/fm-watcher-lock.test.sh').read_text()
records=[]
def processes():
 p=subprocess.run(['ps','-axo','pid=,ppid=,stat=,command='],capture_output=True,text=True,check=True)
 rows={}
 for l in p.stdout.splitlines():
  a=l.strip().split(None,3)
  if len(a)==4:rows[int(a[0])]=(int(a[1]),a[2],a[3])
 return rows
def identity(pid):
 return subprocess.run(['ps','-p',str(pid),'-o','lstart=,command='],capture_output=True,text=True).stdout.strip()
for label,stage,fn,ready in [('startup-handler','handlers','test_watcher_startup_signals_release_lock','startup-ready'),('ln-shim','acquisition','test_watcher_startup_signals_release_lock','startup-ready'),('announcement-hook','returned','test_watcher_interrupted_announcement_recovers','announcement-ready'),('mv-shim','atomic','test_watcher_interrupted_announcement_recovers','announcement-ready')]:
 for version,src in [('baseline',base),('current',current)]:
  text=src.rsplit('\ntest_watcher_check_handoff_preserves_signal_status\n',1)[0]+'\n'
  text=text.replace('for row in modern stock; do','for row in stock; do')
  text=text.replace('for stage in acquisition recovery handlers inherited; do','for stage in '+stage+'; do')
  text=text.replace('for stage in atomic returned polling superseded handling restored; do','for stage in '+stage+'; do')
  driver=root/'tests'/('phase-interrupt-'+label+'-'+version+'.test.sh')
  text=text.replace('kill -"$signal" "$watcher" || fail', 'printf ready > "$dir/suite-ready"\n        builtin kill -STOP "$$"\n        kill -"$signal" "$watcher" || fail')
  driver.write_text(text+fn+'\n')
  tmp=root/'.test-phase'/('interrupt-'+label+'-'+version);tmp.mkdir(exist_ok=True)
  env=os.environ.copy();env.update(TMPDIR=str(tmp),FM_LIVE='0',FM_CLAUDE_LIVE_E2E='0',FM_TEST_STUB_MAX_BLOCK_SECONDS='5')
  p=subprocess.Popen(['/bin/bash',str(driver)],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,start_new_session=True)
  owned={}; fixture=None; watcher=None
  try:
   end=time.monotonic()+12
   while time.monotonic()<end:
    for f in tmp.rglob('suite-ready'):
     if f.stat().st_size:
      fixture=f.parent;watcher=int((fixture/ready).read_text().strip());break
    if fixture:break
    if p.poll() is not None:raise RuntimeError('Suite exited before barrier')
    time.sleep(.05)
   assert fixture is not None, 'Barrier not reached'
   rows=processes(); ids={p.pid,watcher}
   for _ in range(8):
    ids|={pid for pid,v in rows.items() if v[0] in ids}
   owned={pid:identity(pid) for pid in ids}
   before={str(pid):rows.get(pid) for pid in sorted(ids)}
   p.send_signal(signal.SIGTERM)
   p.send_signal(signal.SIGCONT)
   end=time.monotonic()+22
   while p.poll() is None and time.monotonic()<end:time.sleep(.05)
   assert p.poll()==143, ('Suite did not stop with TERM143',p.poll())
   time.sleep(6 if version=='baseline' else 1)
   rows=processes()
   remaining={str(pid):rows[pid] for pid in owned if pid in rows and not rows[pid][1].startswith('Z') and identity(pid)==owned[pid]}
   rec={'barrier':label,'shell':'/bin/bash 3.2','version':version,'suite_status':p.returncode,'fixture_removed':not fixture.exists(),'owned_before_TERM':before,'survivors_after_root_removal':remaining}
   records.append(rec)
   assert not fixture.exists(),rec
   if version=='current':assert not remaining,rec
   else:assert remaining, 'Baseline did not reproduce stranded children'
  finally:
   for pid,ident in reversed(list(owned.items())):
    if identity(pid)==ident:
     try:os.kill(pid,signal.SIGKILL)
     except ProcessLookupError:pass
   if p.poll() is None:p.kill()
   try:output=p.communicate(timeout=3)[0]
   except subprocess.TimeoutExpired:output='Output pipe stayed open after exact fixture process cleanup'
   if records:records[-1]['suite_output']=output
   (ev/'interrupted-fixtures.json').write_text(json.dumps(records,indent=2))
  print(label,version,'survivors',len(remaining),flush=True)
