import os, pathlib, subprocess, time, json, threading
root=pathlib.Path.cwd()
scratch=root/'.validation-sync/manual'
scratch.mkdir(parents=True,exist_ok=True)
ev=root/'bin/fm-busy-event.sh'
base=scratch/'baseline'
base.mkdir(exist_ok=True)
for name in ['fm-busy-event.sh','fm-busy-lib.sh']:
    (base/name).write_bytes(subprocess.check_output(['git','show',f'bb6c9278:bin/{name}']))
os.chmod(base/'fm-busy-event.sh',0o755)
def run(*args, stale=None, binary=ev):
    env=os.environ.copy()
    env.pop('FM_BUSY_LOCK_STALE_SECS',None)
    if stale is not None: env['FM_BUSY_LOCK_STALE_SECS']=stale
    return subprocess.run([str(binary),*map(str,args)],env=env,text=True,capture_output=True,timeout=20)
def arm(name,binary=ev):
    state=scratch/name
    state.mkdir(exist_ok=True)
    r=run('arm',state,'task',binary=binary)
    assert r.returncode==0,r.stderr
    return state,r.stdout.strip()
def retire(state,gen,**kw):
    start=time.monotonic()
    r=run('retire',state,'task','--gen',gen,**kw)
    return r,round(time.monotonic()-start,2)
def log(name,r,elapsed,state,**extra):
    print(json.dumps(dict(scenario=name,exit=r.returncode,elapsed_seconds=elapsed,stdout=r.stdout.strip(),stderr=r.stderr.strip(),remaining=sorted(x.name for x in state.iterdir()),**extra)),flush=True)
state,gen=arm('baseline-orphan',base/'fm-busy-event.sh')
(state/'task.busy-state.lock').mkdir()
r,elapsed=retire(state,gen,stale='12',binary=base/'fm-busy-event.sh')
log('BASELINE first retirement refuses a fresh orphan',r,elapsed,state)
assert r.returncode==1 and 'lock timeout' in r.stderr
state,gen=arm('fixed-configured-orphan')
(state/'task.busy-state.lock').mkdir()
r,elapsed=retire(state,gen,stale='12')
log('TARGET first retirement recovers fresh orphan with 12-second stale threshold',r,elapsed,state)
assert r.returncode==0 and not list(state.iterdir()) and 10<=elapsed<=16
state,gen=arm('fixed-orphan')
(state/'task.busy-state.lock').mkdir()
r,elapsed=retire(state,gen)
log('TARGET first retirement recovers fresh orphan',r,elapsed,state)
assert r.returncode==0 and not list(state.iterdir()) and 3<=elapsed<=8
for setting in [None,'08','bad']:
    state,gen=arm('live-'+str(setting))
    lock=state/'task.busy-state.lock';lock.mkdir()
    holder=lock/'holder';holder.touch()
    result={}
    def wait_retire():result['value']=retire(state,gen,stale=setting)
    worker=threading.Thread(target=wait_retire);worker.start()
    time.sleep(1)
    assert worker.is_alive() and holder.exists() and (state/'task.busy-state').exists()
    holder.unlink();lock.rmdir();worker.join()
    r,elapsed=result['value']
    log('TARGET waits for active lock until holder releases',r,elapsed,state,stale_setting=setting)
    assert r.returncode==0 and not list(state.iterdir())
state,gen=arm('future-lock')
lock=state/'task.busy-state.lock';lock.mkdir()
os.utime(lock,(time.time()+60,time.time()+60))
before={p.name:p.read_bytes() for p in state.iterdir() if p.is_file()}
r,elapsed=retire(state,gen,stale='2')
log('TARGET refuses future-dated lock within timeout without deleting state',r,elapsed,state)
assert r.returncode==1 and 'busy-state lock timeout' in r.stderr and 2<=elapsed<=6
assert before=={p.name:p.read_bytes() for p in state.iterdir() if p.is_file()} and lock.exists()
lock.rmdir()
r,elapsed=retire(state,gen,stale='2')
log('TARGET retirement succeeds after timeout cause is removed',r,elapsed,state)
assert r.returncode==0 and not list(state.iterdir())
print('All direct CLI scenarios completed with their expected persisted-state results.')
