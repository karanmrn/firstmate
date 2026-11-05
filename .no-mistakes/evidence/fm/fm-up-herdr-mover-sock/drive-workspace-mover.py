#!/usr/bin/env python3
"""Drive the production mover against a guarded, workspace-local Herdr lab."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path.cwd()
EVIDENCE = Path('~/.no-mistakes/evidence/01M6PP50ZYJKAGPHE8S1D2HTM2')
LAB = ROOT / '.mover-lab'
HELPER = str(ROOT / 'bin/fm-herdr-lab.sh')
MOVER = str(ROOT / 'bin/backends/herdr-workspace-move.py')
SESSION = f'fm-lab-mover-{os.getpid()}'
env = {k: v for k, v in os.environ.items() if not k.startswith('HERDR_')}
env.update(XDG_CONFIG_HOME='.mover-lab', HOME=str(LAB/'home'),
           FM_HERDR_LAB_STATE_DIR=str(LAB/'guard'),
           HERDR_CONFIG_PATH=str(LAB/'config.toml'), SHELL='/bin/sh')
log = open(EVIDENCE/'live-workspace-mover.log', 'w', buffering=1)
prepared = False
results = []


def write(text):
    print(text, flush=True)
    log.write(text+'\n')


def call(args, expected=0, use_env=True):
    write('$ '+json.dumps(args))
    p = subprocess.run(args, cwd=ROOT, env=env if use_env else None,
                       text=True, capture_output=True, timeout=90)
    if p.stdout:
        write(p.stdout.rstrip())
    if p.stderr:
        write('stderr: '+p.stderr.rstrip())
    write(f'exit={p.returncode}')
    if expected is not None:
        assert p.returncode == expected, (args,p.returncode,expected)
    return p


def lab(*args):
    return call([HELPER, 'run', SESSION, *args])


def snapshot(label):
    p = lab('workspace', 'list')
    data = json.loads(p.stdout)
    (EVIDENCE/(label+'.json')).write_text(json.dumps(data, indent=2)+'\n')
    return data['result']['workspaces']


def ids(rows):
    return [r['workspace_id'] for r in rows]


def focused(rows):
    return [r['workspace_id'] for r in rows if r.get('focused')]


def unchanged(rows, baseline):
    assert ids(rows) == ids(baseline)
    assert focused(rows) == focused(baseline)
    assert {r['workspace_id']:r.get('active_tab_id') for r in rows} == {r['workspace_id']:r.get('active_tab_id') for r in baseline}


try:
    (LAB/'herdr').mkdir(parents=True)
    (LAB/'home').mkdir()
    default_info=json.loads(call([HELPER,'run',SESSION,'session','list','--json'],use_env=False).stdout)
    default=next(s for s in default_info['sessions'] if s['default'])
    (LAB/'herdr'/'herdr.sock').symlink_to(default['socket_path'])
    # provision performs prepare itself for a new session.
    prepared = True
    call([HELPER,'provision',SESSION])
    lab('status','--json')
    sessions = json.loads(lab('session','list','--json').stdout)['sessions']
    own = next(s for s in sessions if s['name']==SESSION)
    assert own['default'] is False and own['running'] is True
    socket_path = ROOT / own['socket_path']
    write(f'Absolute lab socket length: {len(os.fsencode(socket_path))} bytes')
    assert len(os.fsencode(socket_path)) > 108
    seed = snapshot('initial-workspaces')
    assert not seed
    lab('workspace','create','--label','mover-anchor','--cwd',str(LAB/'home'),'--no-focus')
    seed = snapshot('seed-workspace')
    assert len(seed)==1
    created=[]
    for label in ['mover-A','mover-B','mover-C']:
        p=lab('workspace','create','--label',label,'--cwd',str(LAB/'home'),'--no-focus')
        created.append(json.loads(p.stdout)['result']['workspace']['workspace_id'])
    a,b,c=created
    lab('workspace','focus',a)
    before=snapshot('before-long-move')
    original=[seed[0]['workspace_id'],a,b,c]
    assert ids(before)==original
    assert focused(before)==[a]
    baseline=LAB/'baseline-mover.py'
    baseline.write_text(subprocess.run(['git','show','b77b66cb999876c4db19da36b9af5baaacdd52e5:bin/backends/herdr-workspace-move.py'],capture_output=True,text=True,check=True).stdout)
    call([sys.executable,str(baseline),str(socket_path),c,'1'],expected=2)
    unchanged(snapshot('after-baseline-failure'),before)
    moved=call([sys.executable,MOVER,str(socket_path),c,'1'])
    expected=[original[0],c,a,b]
    assert ids(json.loads(moved.stdout)['result']['workspaces'])==expected
    after=snapshot('after-long-move')
    assert ids(after)==expected
    assert focused(after)==[a]
    assert {r['workspace_id']:r['label'] for r in after}=={r['workspace_id']:r['label'] for r in before}
    assert {r['workspace_id']:r['active_tab_id'] for r in after}=={r['workspace_id']:r['active_tab_id'] for r in before}
    results.append({'name':'A workspace moves through a real session socket beyond the AF_UNIX path limit, preserving other workspaces and focus','result':'pass','live':True,'evidence':'live-workspace-mover.log; before-long-move.json; after-baseline-failure.json; after-long-move.json','reason':''})

    short=ROOT/'s'
    assert not short.exists() and not short.is_symlink()
    short.symlink_to(socket_path)
    write(f'Short socket alias length: {len(os.fsencode(short))} bytes')
    assert len(os.fsencode(short)) < 104
    call([sys.executable,MOVER,str(short),c,'0'])
    normal=snapshot('after-short-move')
    assert ids(normal)==[c,original[0],a,b] and focused(normal)==[a]
    assert {r['workspace_id']:r['active_tab_id'] for r in normal}=={r['workspace_id']:r['active_tab_id'] for r in before}
    results.append({'name':'A workspace still moves through a normal-length socket path','result':'pass','live':True,'evidence':'live-workspace-mover.log; after-short-move.json','reason':''})

    special=LAB/('deep socket directory '+'é'*20)
    special.mkdir()
    (special/'herdr.sock').symlink_to(socket_path)
    call([sys.executable,MOVER,str(special/'herdr.sock'),b,'0'])
    weird=snapshot('after-unicode-space-path-move')
    assert ids(weird)==[b,c,original[0],a] and focused(weird)==[a]
    results.append({'name':'A deep socket path with spaces and multibyte characters moves the selected workspace','result':'pass','live':True,'evidence':'live-workspace-mover.log; after-unicode-space-path-move.json','reason':''})

    # Independent safety oracle: rejected input and unreachable sockets must leave live server state unchanged.
    checks=[(str(socket_path),a,'-1',2), (str(socket_path),a,'01',2),
            ('relative.sock',a,'0',2), (str(socket_path),'bad\nworkspace','0',2),
            (str(LAB/'missing-directory'/'herdr.sock'),a,'0',2),
            (str(socket_path.parent/'absent.sock'),a,'0',2),
            (str(socket_path),'nonexistent-workspace-id','0',4)]
    for path,workspace,index,code in checks:
        call([sys.executable,MOVER,path,workspace,index],expected=code)
        unchanged(snapshot('after-rejected-request'),weird)
    results.append({'name':'Invalid move requests and unavailable sockets fail without reordering the live session','result':'pass','live':True,'evidence':'live-workspace-mover.log; after-rejected-request.json','reason':''})
except Exception as exc:
    write('DRIVER FAILURE: '+repr(exc))
    raise
finally:
    teardown_ok=False
    if prepared:
        try:
            call([HELPER,'teardown',SESSION])
            remaining=json.loads(lab('session','list','--json').stdout)['sessions']
            assert not any(s['name']==SESSION for s in remaining)
            teardown_ok=True
            write('Teardown confirmed: lab session absent and default-session tripwire unchanged.')
        except Exception as exc:
            write('TEARDOWN FAILURE: '+repr(exc))
    (EVIDENCE/'live-scenarios.json').write_text(json.dumps({'scenarios':results,'teardown_ok':teardown_ok},indent=2)+'\n')
    if teardown_ok:
        short=ROOT/'s'
        if short.is_symlink():
            short.unlink()
        shutil.rmtree(LAB)
    log.close()
    if prepared and not teardown_ok:
        raise RuntimeError('Lab teardown could not be confirmed')
