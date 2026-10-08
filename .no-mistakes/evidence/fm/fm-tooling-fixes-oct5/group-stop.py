import subprocess,os,signal,time,json,shutil
from pathlib import Path
root=Path.cwd();phase=root/'.test-phase'; ev=Path('/Users/karanmanoharan/.no-mistakes/evidence/01M4DR9JRJQ9KWVJ2ZGHKNTQNR')
b=phase/'baseline-bin';b.mkdir()
for f in (root/'bin').iterdir():
 if f.is_file() and f.name!='fm-watch.sh':(b/f.name).symlink_to(f)
src=subprocess.run(['git','show','ab8d03ad1360baf4edeed3a1c57867d2e8237092:bin/fm-watch.sh'],capture_output=True,text=True,check=True).stdout
(b/'fm-watch.sh').write_text(src)
records=[]
for version,watch in [('baseline',b/'fm-watch.sh'),('current',root/'bin/fm-watch.sh')]:
 for sig in ['HUP','TERM']:
  home=phase/('group-'+version+'-'+sig)
  subprocess.run(['bin/fm-lab-home.sh','create',str(home)],check=True,capture_output=True)
  fake=home/'fakebin';fake.mkdir();(fake/'tmux').write_text('#!/bin/sh\nexit 0\n');(fake/'tmux').chmod(0o700)
  env=os.environ.copy()
  for k in ['FM_ROOT_OVERRIDE','FM_STATE_OVERRIDE','FM_DATA_OVERRIDE','FM_CONFIG_OVERRIDE','FM_PROJECTS_OVERRIDE','FM_GATE_REFUSE_BYPASS','BASH_ENV']:env.pop(k,None)
  env.update(FM_HOME=str(home),PATH=str(fake)+':'+env['PATH'],FM_POLL='1',FM_SIGNAL_GRACE='0',FM_CHECK_INTERVAL='999999',FM_HEARTBEAT='999999',FM_LIVE='0',FM_CLAUDE_LIVE_E2E='0')
  p=subprocess.Popen(['/bin/bash',str(watch)],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,start_new_session=True)
  try:
   end=time.monotonic()+10
   while not (home/'state/.last-watcher-beat').exists() and time.monotonic()<end:
    assert p.poll() is None,'Watcher exited before polling'
    time.sleep(.05)
   assert (home/'state/.last-watcher-beat').exists(),'No running watcher beacon'
   owner=(home/'state/.watch.lock/pid').read_text().strip();assert owner==str(p.pid)
   os.killpg(p.pid,getattr(signal,'SIG'+sig))
   output=p.communicate(timeout=15)[0]
   marker=home/'state/.watcher-down'
   rec={'version':version,'shell':'/bin/bash 3.2','signal':sig,'signal_target':'entire isolated watcher process group','status':p.returncode,'owned_lock_before_signal':owner,'lock_after_signal':(home/'state/.watch.lock').exists(),'marker_after_signal':marker.read_text() if marker.exists() else None,'output':output}
   records.append(rec)
   if version=='current':
    assert p.returncode=={'HUP':129,'TERM':143}[sig],rec
    assert not rec['lock_after_signal'],rec
    assert rec['marker_after_signal'].startswith('pending:downtime:'),rec
  finally:
   if p.poll() is None:
    os.killpg(p.pid,signal.SIGKILL);p.communicate()
   shutil.rmtree(home)
  (ev/'native-group-stop.json').write_text(json.dumps(records,indent=2))
  print(version,sig,'status',p.returncode,'lock retained',rec['lock_after_signal'],flush=True)
