import os, pathlib, subprocess, time, json, hashlib
root = pathlib.Path.cwd()
evidence = pathlib.Path('~/.no-mistakes/evidence/01M6R6KB9XA7SCMD2KK68R7TZJ')
work = root / '.test-when-validation'
baseenv = os.environ.copy()
for key in list(baseenv):
    if key.startswith('FM_') or key.startswith('HERDR_'):
        baseenv.pop(key)
baseenv['FM_PROCEVENT_CLAIM_ROOT'] = str(work / 'claims')
baseenv['TMPDIR'] = str(work)
logs = []
homes = []
results = []
def run(home, tool, *args, ok=True):
    env = baseenv | {'FM_HOME': str(home)}
    p = subprocess.run([str(root/'bin'/tool), *map(str,args)], cwd=root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    logs.append('$ FM_HOME=' + str(home.relative_to(root)) + ' ' + tool + ' ' + ' '.join(map(str,args)) + '\n' + p.stdout + p.stderr + 'exit=' + str(p.returncode))
    if ok and p.returncode != 0:
        raise AssertionError(logs[-1])
    return p

def home(name):
    h=work/name
    run(h, 'fm-lab-home.sh', 'create', h)
    homes.append(h)
    return h

def wait(fn, description):
    for _ in range(150):
        if fn(): return
        time.sleep(.1)
    raise AssertionError('timeout: '+description)

def check(value, text):
    if not value: raise AssertionError(text)
    logs.append('Verified: '+text)

def scenario(name, fn):
    logs.append('\nSCENARIO: '+name)
    try:
        fn()
        results.append({'name':name,'result':'pass','live':True})
    except Exception as e:
        logs.append('FAIL: '+str(e))
        results.append({'name':name,'result':'fail','live':True,'error':str(e)})

cond=work/'condition.sh'
cond.write_text('#!/bin/bash\necho poll >> "$1"\ntest -e "$2"\n')
act=work/'action.sh'
act.write_text('#!/bin/bash\necho fired >> "$1"\necho action-completed\n')
cond.chmod(0o755);act.chmod(0o755)

def arm(h,name,tool='fm-procevent-when.sh'):
    return run(h,tool,'arm',name,'--interval','0.1','--stable','1','--condition',cond,h/(name+'.poll'),h/(name+'.trigger'),'--action',act,h/(name+'.action'))

def clean(h,sid):
    for suffix in ['spec','trust','fired']:
        check(not (h/'state/when'/f'{sid}.{suffix}').exists(),f'{sid}.{suffix} is absent')
    for suffix in ['source','runner']:
        check(not (h/'state/procevent'/f'{sid}.{suffix}').exists(),f'{sid}.{suffix} is absent')

def baseline():
    h=home('baseline');arm(h,'listed','.fm-when-base-validation.sh')
    listing=run(h,'fm-procevent.sh','list').stdout
    sid=next(line.split()[0] for line in listing.splitlines() if line.startswith('when-listed '))
    out=run(h,'.fm-when-base-validation.sh','retire',sid).stdout
    check('retired: when-when-listed' in out,'base retires the wrong double-prefixed ID')
    check((h/'state/procevent/when-listed.source').exists(),'base leaves the listed watch registered')
    logs.append('Baseline reproduces the reported failure.')

def collision():
    h=home('collision');arm(h,'listed');arm(h,'when-listed')
    run(h,'fm-procevent.sh','reconcile')
    wait(lambda: all((h/(n+'.poll')).exists() for n in ['listed','when-listed']),'both conditions polling')
    listing=run(h,'fm-procevent.sh','list').stdout
    check(all(any(l.split()[:3]==[sid,'when','live'] for l in listing.splitlines()) for sid in ['when-listed','when-when-listed']),'both overlapping watches have live owners')
    sid=next(l.split()[0] for l in listing.splitlines() if l.split()[:1]==['when-listed'])
    run(h,'fm-procevent-when.sh','retire',sid);clean(h,sid)
    run(h,'fm-procevent-when.sh','retire',sid)
    listing=run(h,'fm-procevent.sh','list').stdout
    check(any(l.split()[:3]==['when-when-listed','when','live'] for l in listing.splitlines()),'exact-ID retirement and retry preserve the double-prefixed sibling')
    (h/'listed.trigger').touch();(h/'when-listed.trigger').touch()
    wait(lambda:(h/'when-listed.action').exists(),'sibling action fires')
    wait(lambda:any((h/'state/procevent-inbox').glob('when-when-listed.*.result')),'sibling outcome captured')
    time.sleep(.3)
    check(not (h/'listed.action').exists(),'retired watch never executes after its condition becomes true')
    run(h,'fm-procevent-when.sh','retire','when-when-listed');clean(h,'when-when-listed')

def bare_retry():
    h=home('bare');arm(h,'plain')
    run(h,'fm-procevent-when.sh','retire','plain');clean(h,'when-plain')
    run(h,'fm-procevent-when.sh','retire','plain')
    run(h,'fm-procevent-when.sh','retire','when-absent')
    check(run(h,'fm-procevent.sh','list').stdout.strip()=='no sources registered','bare retirement and absent-ID retries leave no registrations')

def long_id():
    h=home('length');name='a'*59;arm(h,name)
    sid=next(l.split()[0] for l in run(h,'fm-procevent.sh','list').stdout.splitlines() if l.startswith('when-'))
    check(len(sid)==64,'list exposes the full 64-character ID')
    run(h,'fm-procevent-when.sh','retire',sid);clean(h,sid)
    run(h,'fm-procevent-when.sh','retire',sid)

def invalid():
    h=home('invalid');arm(h,'guard')
    before={str(p.relative_to(h)):p.read_bytes() for p in (h/'state').rglob('*') if p.is_file()}
    for arg in ['when-','when-../guard','../guard','when-'+'a'*60]:
        p=run(h,'fm-procevent-when.sh','retire',arg,ok=False)
        check(p.returncode!=0,'unsafe or oversized argument is refused: '+arg)
    after={str(p.relative_to(h)):p.read_bytes() for p in (h/'state').rglob('*') if p.is_file()}
    check(before==after,'invalid retirement arguments leave all persisted home files unchanged')

def preserve():
    h=home('preserve');arm(h,'done');(h/'done.trigger').touch()
    run(h,'fm-procevent.sh','reconcile')
    wait(lambda:any((h/'state/procevent-inbox').glob('when-done.*.result')),'completed result')
    wait(lambda:not(h/'state/procevent/when-done.source').exists(),'terminal retirement')
    run(h,'fm-procevent.sh','handled','when-done','1')
    inbox=h/'state/procevent-inbox'
    before={p.name:p.read_bytes() for p in inbox.iterdir() if p.is_file()}
    logs.append('Captured result:\n'+(inbox/'when-done.1.result').read_text())
    check(any(n.endswith('.handled') for n in before),'a durable handled acknowledgement exists')
    run(h,'fm-procevent-when.sh','retire','when-done');clean(h,'when-done')
    run(h,'fm-procevent-when.sh','retire','when-done')
    check(before=={p.name:p.read_bytes() for p in inbox.iterdir() if p.is_file()},'exact-ID retirement preserves captured results and handled acknowledgements byte-for-byte')

try:
    baseline()
    scenario('Retire a listed live ID without retiring its double-prefixed sibling',collision)
    scenario('Retire by bare name and repeat retirement of absent watches',bare_retry)
    scenario('Retire and retry the maximum-length listed ID',long_id)
    scenario('Reject unsafe and oversized IDs without changing watch state',invalid)
    scenario('Retire a completed watch while retaining its outcome and acknowledgement',preserve)
finally:
    for h in homes:
        try:
            run(h,'fm-procevent.sh','sweep-home')
        except Exception as e:
            results.append({'name':'Dispose of lab runners','result':'fail','live':True,'error':str(e)})
    (evidence/'live-retire-transcript.log').write_text('\n'.join(logs)+'\n')
    (evidence/'live-retire-results.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,indent=2))
raise SystemExit(0 if results and all(r['result']=='pass' for r in results) else 1)
