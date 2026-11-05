import json, os, pathlib, subprocess, sys, time
root=pathlib.Path.cwd()
evidence=pathlib.Path('~/.no-mistakes/evidence/01M6PDZYA64HDM467VSQB64MAM')
log=open(evidence/'workspace-mover-live.log','w')
env=os.environ.copy()
for key in list(env):
    if key.startswith('HERDR_') or key in ('FM_HOME','FM_ROOT_OVERRIDE','FM_STATE_OVERRIDE','FM_DATA_OVERRIDE','FM_CONFIG_OVERRIDE','FM_PROJECTS_OVERRIDE'):
        env.pop(key,None)
for kind in ('CONFIG','STATE','DATA','CACHE'):
    env['XDG_'+kind+'_HOME']='.test-mover-lab/'+{'CONFIG':'xdg','STATE':'state','DATA':'data','CACHE':'cache'}[kind]
env['HOME']=str(root/'.test-mover-lab/home')
env['SHELL']='/bin/sh'
env['FM_HERDR_LAB_STATE_DIR']=str(root/'.test-mover-lab/tripwires')
helper=str(root/'bin/fm-herdr-lab.sh')
mover=str(root/'bin/backends/herdr-workspace-move.py')
session='fm-lab-mover-'+str(os.getpid())
results=[]
prepared=False

def run(args, expected=0):
    log.write('$ '+ ' '.join(map(str,args))+'\n');log.flush()
    p=subprocess.run(list(map(str,args)),env=env,cwd=root,capture_output=True,text=True,timeout=80)
    log.write(p.stdout+p.stderr+'[exit '+str(p.returncode)+']\n');log.flush()
    print(' '.join(map(str,args[-4:]))+': exit '+str(p.returncode),flush=True)
    if expected is not None and p.returncode!=expected:
        raise AssertionError('expected exit '+str(expected)+', got '+str(p.returncode))
    return p

def lab(*args):
    return run([helper,'run',session,*args])

def snapshot():
    return json.loads(lab('workspace','list').stdout)

def order(s):
    return [w['workspace_id'] for w in s['result']['workspaces']]

def active(s):
    return [w['workspace_id'] for w in s['result']['workspaces'] if w.get('focused')]

try:
    prepared=True
    run([helper,'provision',session])
    status=json.loads(lab('status','--json').stdout)
    assert status['server']['running']
    created=[]
    for label in ('parent','foreign','target'):
        data=json.loads(lab('workspace','create','--cwd',root,'--label',label,'--no-focus').stdout)
        created.append(data['result']['workspace']['workspace_id'])
    parent,foreign,target=created
    lab('workspace','focus',parent)
    before=snapshot()
    assert order(before)==created and active(before)==[parent], before
    sock=root/status['server']['socket']
    assert len(os.fsencode(sock))>108
    log.write('Long absolute socket length: '+str(len(os.fsencode(sock)))+' bytes\n')
    baseline=root/'.test-mover-lab/baseline.py'
    baseline.write_bytes(subprocess.check_output(['git','show','4869cf58e36b4fe9113cc3684648ed4e9fb4d0dc:bin/backends/herdr-workspace-move.py']))
    run([sys.executable,baseline,sock,target,1],expected=2)
    assert order(snapshot())==created
    run([mover,sock,target,1])
    after=snapshot()
    assert order(after)==[parent,target,foreign],after
    assert active(after)==active(before),after
    results.append({'name':'Move a projected workspace through a socket path longer than the AF_UNIX limit, preserving sibling order and focus','result':'pass','live':True,'evidence':'workspace-mover-live.log','reason':'The base mover returned 2. The target mover returned 0 and the real Herdr workspace list showed the exact requested order.'})
    alias=root/'.mover.sock'
    alias.unlink(missing_ok=True)
    alias.symlink_to(sock)
    assert len(os.fsencode(alias))<104
    run([mover,alias,foreign,1])
    restored=snapshot()
    assert order(restored)==created and active(restored)==active(before)
    results.append({'name':'Move through an ordinary short absolute socket path without changing focus','result':'pass','live':True,'evidence':'workspace-mover-live.log','reason':'A short socket alias reached the same real lab server and restored the original order.'})
    for path,ws,index,rc in ((sock,'missing-workspace',0,4),(sock,target,-1,2),('relative.sock',target,0,2),(root/'.test-mover-lab/missing/herdr.sock',target,0,2),(root/'.test-mover-lab/xdg',target,0,2)):
        run([mover,path,ws,index],expected=rc)
        unchanged=snapshot()
        assert order(unchanged)==created and active(unchanged)==active(before)
    for ws in created:
        lab('workspace','get',ws)
    lab('pane','list')
    results.append({'name':'Reject invalid paths, a negative index, and an unknown workspace without changing the lab layout','result':'pass','live':True,'evidence':'workspace-mover-live.log','reason':'Each rejected request returned its documented error and the real workspace inventory retained every workspace and its focus.'})
except Exception as exc:
    log.write('DRIVER FAILURE: '+repr(exc)+'\n');log.flush()
    print(repr(exc),file=sys.stderr)
    results.append({'name':'Complete real Herdr workspace mover validation','result':'fail','live':prepared,'evidence':'workspace-mover-live.log','reason':repr(exc)})
finally:
    if prepared:
        try:
            run([helper,'teardown',session])
            log.write('Guarded teardown completed with the default-session tripwire unchanged.\n')
        except Exception as exc:
            results.append({'name':'Tear down the disposable lab with its fleet tripwire intact','result':'fail','live':True,'evidence':'workspace-mover-live.log','reason':repr(exc)})
    (evidence/'workspace-mover-results.json').write_text(json.dumps({'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'session':session,'scenarios':results},indent=2)+'\n')
    log.close()
sys.exit(1 if any(x['result']=='fail' for x in results) else 0)
