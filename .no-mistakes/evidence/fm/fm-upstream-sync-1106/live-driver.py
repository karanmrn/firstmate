import os, pathlib, subprocess, time, json, shutil
ROOT=pathlib.Path.cwd()
WORK=ROOT/'.validation/live'
EVIDENCE=pathlib.Path('~/.no-mistakes/evidence/01M6QTN1QRJBQB6CZV1FA5ZVZJ')
WORK.mkdir()
env=os.environ.copy()
for key in list(env):
    if key.startswith('FM_') or key in ('LAVISH_AXI_STATE_DIR','TMUX'):
        env.pop(key)
env['TMPDIR']=str(ROOT/'.validation/tmp')
log=[]
def note(s):
    print(s,flush=True)
    log.append(s)
def call(args,e,check=True):
    p=subprocess.run([str(a) for a in args],env=e,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=40)
    note('$ '+ ' '.join(str(a) for a in args)+'\nexit='+str(p.returncode)+'\n'+p.stdout+p.stderr)
    if check: assert p.returncode==0
    return p
homes=[]
def home(name):
    h=WORK/name
    subprocess.run([str(ROOT/'bin/fm-lab-home.sh'),'create',str(h)],env=env,check=True,stdout=subprocess.DEVNULL)
    homes.append(h)
    return h
try:
    h=home('export')
    out=WORK/'exported records'
    (h/'config/record-export-root').write_text(str(out)+'\n')
    (h/'data/projects.md').write_text('Independent fixture project\n')
    (h/'state/task-a.status').write_text('working: export fixture\n')
    (h/'state/.startup-network.status').write_text('private network status\n')
    (h/'state/.internal.meta').symlink_to(h/'data/projects.md')
    (h/'state/.internal.inbox').mkdir()
    e=env | {'FM_HOME':str(h),'FM_ROOT_OVERRIDE':'','FM_STATE_OVERRIDE':'','FM_DATA_OVERRIDE':'','FM_CONFIG_OVERRIDE':''}
    call([ROOT/'bin/fm-record-export.sh','sync'],e)
    assert (out/'live/data/projects.md').read_bytes()==(h/'data/projects.md').read_bytes()
    assert (out/'live/state/task-a.status').read_bytes()==(h/'state/task-a.status').read_bytes()
    records=sorted(str(p.relative_to(out/'live')) for p in (out/'live').rglob('*'))
    assert not any('/.' in '/'+p for p in records)
    note('Exported public snapshot: '+json.dumps(records))
    note('Task status: '+(out/'live/state/task-a.status').read_text().strip())
    alternate=WORK/'alternate-data'; alternate.mkdir()
    (alternate/'projects.md').write_text('Explicit override project\n')
    call([ROOT/'bin/fm-record-export.sh','sync'],e|{'FM_DATA_OVERRIDE':str(alternate)})
    assert (out/'live/data/projects.md').read_text()=='Explicit override project\n'
    note('Explicit nonempty data override exported: '+(out/'live/data/projects.md').read_text().strip())
    for mode in ('ensure-listening','reconcile','inherited'):
        h=home(mode)
        marker=h/'command-started'
        e=env|{'FM_HOME':str(h),'FM_PROCEVENT_CLAIM_ROOT':str(WORK/(mode+'-claims')),'FM_PROCEVENT_OWNER_LEASE_SECONDS':'2','FM_PROCEVENT_OWNER_CHECK_SECONDS':'1'}
        pe=[ROOT/'bin/fm-procevent.sh']
        import sys
        call(pe+['register','when','live-source','--',sys.executable,'-c',"import pathlib,time; pathlib.Path(__import__('sys').argv[1]).write_text('source command executed'); time.sleep(30)",str(marker)],e)
        lease=h/'state/procevent/.owner-lease'
        time.sleep(3.1)
        before=lease.read_text()
        note(mode+' lease age before request: '+str(round(time.monotonic()-float(before),3))+' seconds')
        if mode=='inherited':
            p=call(pe+['ensure-listening','live-source'],e|{'FM_PROCEVENT_IN_RUNNER':'1'},False)
            time.sleep(4)
            assert lease.read_text()==before and not marker.exists()
            note('Inherited runner refused startup and left the expired owner lease unchanged.')
        else:
            if mode=='reconcile':
                inbox=h/'state/procevent-inbox'; inbox.mkdir(exist_ok=True)
                for i in range(90):
                    (inbox/f'pending-{i}.1.result').write_text(f'when: pending-{i}\nstatus: fired\ndetail: disposable replay record\ncondition_polls: 1\naction_exit: 0\noutput:\n')
                    (inbox/f'pending-{i}.1.adapter').write_text('when\n')
                    (inbox/f'pending-{i}.1.result').chmod(0o600)
                    (inbox/f'pending-{i}.1.adapter').chmod(0o600)
            start=time.monotonic()
            call(pe+[mode]+(['live-source'] if mode=='ensure-listening' else []),e)
            elapsed=time.monotonic()-start
            note(mode+' request duration: '+str(round(elapsed,3))+' seconds')
            deadline=time.monotonic()+5
            while not marker.exists() and time.monotonic()<deadline:
                time.sleep(.05)
            assert marker.exists() and lease.read_text()!=before
            if mode=='reconcile': assert elapsed>3
            call(pe+['list'],e)
            pid=int((h/'state/procevent/live-source.runner').read_text())
            deadline=time.monotonic()+12
            while True:
                try: os.kill(pid,0)
                except ProcessLookupError: break
                assert time.monotonic()<deadline, 'runner did not stop after lease expiry'
                time.sleep(.1)
            note(mode+' source executed and runner '+str(pid)+' stopped after owner renewal ceased.')
        call(pe+['retire','live-source'],e)
        call(pe+['sweep-home'],e)
    note('All live CLI scenarios passed. All disposable process-event homes were swept.')
finally:
    for h in homes:
        e=env|{'FM_HOME':str(h),'FM_PROCEVENT_CLAIM_ROOT':str(WORK/(h.name+'-claims'))}
        if (h/'state/procevent').exists():
            p=subprocess.run([str(ROOT/'bin/fm-procevent.sh'),'sweep-home'],env=e,text=True,capture_output=True,timeout=30)
            note('Final cleanup '+h.name+': exit='+str(p.returncode)+' '+p.stdout+p.stderr)
            assert p.returncode==0
    (EVIDENCE/'live-cli-transcript.log').write_text('\n'.join(log)+'\n')
    shutil.rmtree(WORK)
