import pathlib, subprocess, os, shutil
r=pathlib.Path.cwd(); w=r/'.validation/export-regression'; w.mkdir()
b=w/'baseline/bin'; b.mkdir(parents=True)
for name in ('fm-record-export.sh','fm-record-export.py'):
    p=b/name
    p.write_bytes(subprocess.check_output(['git','show','fadd59641a5d0162c2ed5d1ec94d7eb7db6cdaee:bin/'+name]))
    p.chmod(0o755)
env={k:v for k,v in os.environ.items() if not k.startswith('FM_')}
log=[]
try:
    for scenario in ('empty-overrides','hidden-state'):
        h=w/scenario
        for d in ('config','data','state'): (h/d).mkdir(parents=True)
        out=w/(scenario+'-export')
        (h/'config/record-export-root').write_text(str(out)+'\n')
        (h/'data/projects.md').write_text('regression project\n')
        (h/'state/task.status').write_text('working\n')
        e=env|{'FM_HOME':str(h)}
        if scenario=='empty-overrides':
            e|={k:'' for k in ('FM_ROOT_OVERRIDE','FM_CONFIG_OVERRIDE','FM_DATA_OVERRIDE','FM_STATE_OVERRIDE')}
        else: (h/'state/.startup-network.status').write_text('private startup\n')
        for phase,cli in [('base',b/'fm-record-export.sh'),('target',r/'bin/fm-record-export.sh')]:
            p=subprocess.run([str(cli),'sync'],env=e,text=True,capture_output=True,timeout=20)
            works=p.returncode==0 and (out/'live/state/task.status').exists()
            row=f'{scenario} {phase}: exit={p.returncode}, task_exported={works}, stderr={p.stderr.strip()}'
            print(row); log.append(row)
            assert works==(phase=='target')
finally:
    pathlib.Path('~/.no-mistakes/evidence/01M6QTN1QRJBQB6CZV1FA5ZVZJ/export-regression.log').write_text('\n'.join(log)+'\n')
    shutil.rmtree(w)
