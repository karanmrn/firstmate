import json,os,pathlib,shutil,subprocess,time
root=pathlib.Path.cwd()
out=pathlib.Path('~/.no-mistakes/evidence/01M6RYVFH7BH12KJMDCASDZAXK')
socket=str(root/'.s')
hook=root/'.test-tmp/cli-hook.py'
hook.write_text(hook.read_text().replace("root=pathlib.Path(os.environ['LIVE_SOURCE'])", "if os.environ.get('LIVE_TEST_ID'): env['CODEX_SESSION_ID']=os.environ['LIVE_TEST_ID']\nroot=pathlib.Path(os.environ['LIVE_SOURCE'])"))
env={k:v for k,v in os.environ.items() if not k.startswith(('FM_','CODEX_','CLAUDE_','HERDR_')) and k not in ('NO_MISTAKES_GATE','TMUX','TMUX_PANE')}
cases=[
('plain-cli',['--no-daemon'],False),
('crewmate-cli',['--no-daemon','-m','fixture','-c','model_reasoning_effort="xhigh"','--dangerously-bypass-approvals-and-sandbox','--disable','hooks','-c','notify=["bash","-c","true"]'],False),
('secondmate-cli',['--no-daemon','-m','fixture','--approve-for-me'],False),
('embedded-cli-with-id',['--no-daemon','--no-alt-screen','-a','never','-s','danger-full-access'],True)]
for label,flags,identity in cases:
 h=root/'.test-tmp'/label
 subprocess.run([str(root/'bin/fm-lab-home.sh'),'create',str(h)],env=env,check=True,capture_output=True)
 (h/'tmux').mkdir()
 (h/'provider').mkdir()
 config='model_provider="fixture"\nmodel="fixture"\n[features]\nhooks=true\n[model_providers.fixture]\nname="fixture"\nbase_url="http://127.0.0.1:1/v1"\nwire_api="responses"\nrequires_openai_auth=false\nrequest_max_retries=0\nstream_max_retries=0\n'
 config+='[projects.'+json.dumps(str(root))+']\ntrust_level="trusted"\n'
 (h/'provider/config.toml').write_text(config)
 (h/'provider/hooks.json').write_text(json.dumps({'hooks':{'SessionStart':[{'hooks':[{'type':'command','command':str(hook),'timeout':60}]}]}}))
 runenv=env|{'TMUX_TMPDIR':str(h/'tmux')}
 args=['tmux','-S',socket,'new-session','-d','-s','primary','-x','120','-y','40','-c',str(root)]
 for k,v in {'FM_HOME':str(h),'CODEX_HOME':str(h/'provider'),'LIVE_SOURCE':str(root),'TMPDIR':str(root/'.test-tmp'),'LIVE_TEST_ID':'00000000-0000-4000-8000-000000000111' if identity else ''}.items():
  args+=['-e',k+'='+v]
 launch=['codex']+flags+['--dangerously-bypass-hook-trust','-C',str(h),'FIRSTMATE_OP: Inspect codex app-server ownership']
 # Hooks are disabled in the actual crewmate shape. Keep that case as a real
 # launch proof, then use the TUI shell via a trusted local hook on a second
 # ordinary option-first invocation with the same value-taking flags.
 if label=='crewmate-cli':
  launch[launch.index('--disable')]='--enable'
 started=False
 try:
  subprocess.run(args+launch,env=runenv,check=True,capture_output=True)
  started=True
  for _ in range(300):
   if (h/'result.json').exists(): break
   time.sleep(.1)
  else:
   pane=subprocess.run(['tmux','-S',socket,'capture-pane','-p','-t','primary'],env=runenv,text=True,capture_output=True)
   (out/(label+'-pane.txt')).write_text(pane.stdout+pane.stderr)
   raise AssertionError(label+': no hook result')
  result=json.loads((h/'result.json').read_text())
  result['launch']=launch
  result['pty_grid']='40 rows x 120 columns'
  (out/(label+'-result.json')).write_text(json.dumps(result,indent=2))
  assert result['returncode']==0 and result['lock'] and result['identity'] is None,result
  pane=subprocess.run(['tmux','-S',socket,'capture-pane','-p','-t','primary'],env=runenv,text=True,capture_output=True,check=True)
  (out/(label+'-pane.txt')).write_text(pane.stdout)
  print(label+': '+result['stdout'].strip()+'; native sidecar absent',flush=True)
 finally:
  if started:
   subprocess.run(['tmux','-S',socket,'kill-server'],env=runenv,check=True,capture_output=True)
  shutil.rmtree(h)
