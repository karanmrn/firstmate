import pathlib,subprocess,os,time,shutil,sys
r=pathlib.Path.cwd(); w=r/'.validation/lease-regression'; w.mkdir()
b=w/'bin'; shutil.copytree(r/'bin',b,symlinks=True)
p=b/'fm-procevent.sh'
p.write_bytes(subprocess.check_output(['git','show','fadd59641a5d0162c2ed5d1ec94d7eb7db6cdaee:bin/fm-procevent.sh'])); p.chmod(0o755)
env={k:v for k,v in os.environ.items() if not k.startswith('FM_') and k!='TMUX'}
log=[]
try:
    for phase,cli in [('base',p),('target',r/'bin/fm-procevent.sh')]:
        h=w/phase
        subprocess.run([str(r/'bin/fm-lab-home.sh'),'create',str(h)],env=env,check=True,capture_output=True)
        e=env|{'FM_HOME':str(h),'FM_ROOT_OVERRIDE':str(w if phase=='base' else r),'FM_PROCEVENT_CLAIM_ROOT':str(w/(phase+'-claims')),'FM_PROCEVENT_OWNER_LEASE_SECONDS':'2','FM_PROCEVENT_OWNER_CHECK_SECONDS':'1'}
        marker=h/'started'
        try:
            subprocess.run([str(cli),'register','when','regression','--',sys.executable,'-c',"import pathlib,time,sys; pathlib.Path(sys.argv[1]).write_text('executed'); time.sleep(30)",str(marker)],env=e,check=True,capture_output=True)
            time.sleep(3.1)
            old=(h/'state/procevent/.owner-lease').read_text()
            result=subprocess.run([str(cli),'ensure-listening','regression'],env=e,capture_output=True,text=True,timeout=15)
            time.sleep(3)
            launched=marker.exists()
            refreshed=(h/'state/procevent/.owner-lease').read_text()!=old
            row=f'{phase} ensure-listening after lease expiry: exit={result.returncode}, command_executed={launched}, lease_refreshed={refreshed}'
            print(row,flush=True); log.append(row)
            assert launched==(phase=='target') and refreshed==(phase=='target')
        finally:
            for attempt in range(5):
                cleanup=subprocess.run([str(cli),'sweep-home'],env=e,capture_output=True,text=True,timeout=30)
                if cleanup.returncode==0: break
                time.sleep(1)
            assert cleanup.returncode==0,cleanup.stderr
            log.append(phase+' cleanup: '+cleanup.stdout.strip())
finally:
    pathlib.Path('~/.no-mistakes/evidence/01M6QTN1QRJBQB6CZV1FA5ZVZJ/lease-regression.log').write_text('\n'.join(log)+'\n')
    shutil.rmtree(w)
