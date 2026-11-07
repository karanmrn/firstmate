import assert from 'node:assert/strict';
import fs from 'node:fs';
import {spawnSync} from 'node:child_process';
import {McpSession, readCredential, gate} from '../bin/fm-t3-mcp.mjs';
const root=process.cwd();
const variant=process.argv[2]||'nightly';
const token=root+'/.validation-t3/'+(variant==='nightly'?'token':variant+'-token');
const log='~/.no-mistakes/evidence/01M6TW2N0WHAV0YP4KA3JWP9YW/'+variant+'-live.jsonl';
function record(x){fs.appendFileSync(log,JSON.stringify(x)+'\n');console.log(JSON.stringify(x));}
function cli(verb,args=[],expected=0,tokenPath=token){
 const p=spawnSync('node',['bin/fm-t3-mcp.mjs',verb,...args,'--token-file',tokenPath],{encoding:'utf8',timeout:60000});
 const out=p.stdout.trim();record({verb,args,exit:p.status,output:out,stderr:p.stderr.trim()});
 assert.equal(p.status,expected);return JSON.parse(out);
}
const c=readCredential(token), s=new McpSession(c.origin,c.access_token);
let tid;
try{
 const g=await gate(s,c); record({serverVersion:g.serverVersion,tools:g.tools.filter(t=>/configuration|configure|pending_request/.test(t))});
 if(variant==='legacy'){
  assert(g.tools.includes('t3_thread_configure')&&g.tools.includes('t3_thread_configuration'));
 }
 cli('status');
 const p=cli('project-ensure',['--root',root+'/.validation-t3/project']);
 const cat=await s.call('orchestrator_capabilities',{});
 const provider=cat.providers.find(p=>p.providerInstanceId==='claudeAgent');
 record({catalog:provider});
 const visible=provider.models.find(m=>m.id==='claude-haiku-5-5')||provider.models[0];
 const sel=cli('resolve-selection',['--harness','claude','--instance','claudeAgent','--model',visible.id,'--effort','low','--project',p.projectId]).selection;
 assert.equal(sel.options.find(o=>o.id==='effort').value,'low');
 if(variant!=='legacy'){
  assert(provider.omittedModels>0);
  assert(!provider.models.some(m=>m.id==='claude-sonnet-4-6'));
  const hidden=cli('resolve-selection',['--harness','claude','--instance','claudeAgent','--model','claude-sonnet-4-6','--effort','high']);
  assert.equal(hidden.selection.model,'claude-sonnet-4-6');
  await s.call('t3_project_update',{projectId:p.projectId,defaultModelSelection:{instanceId:'claudeAgent',model:'claude-opus-5-5',options:[{id:'fastMode',value:true}]}});
  const def=cli('resolve-selection',['--harness','claude','--instance','claudeAgent','--model','default','--effort','low','--project',p.projectId]);
  assert.deepEqual(def.selection.options,[{id:'fastMode',value:true},{id:'effort',value:'low'}]);
 }
 assert.equal(cli('resolve-selection',['--harness','claude','--instance','claudeAgent','--model',visible.id,'--effort','invalid'],4).error.code,'effort_unsupported');
 assert.equal(cli('resolve-selection',['--harness','claude','--instance','claudeAgent','--model','no-such-model-validation','--effort','default'],4).error.code,'model_unknown');
 const mismatch=root+'/.validation-t3/'+variant+'-mismatch-token';fs.writeFileSync(mismatch,JSON.stringify({...c,environment_id:'different-lab-environment'}),{mode:0o600});
 const refused=cli('project-ensure',['--root',root+'/.validation-t3/should-not-exist'],4,mismatch);
 assert.equal(refused.error.code,'environment_mismatch');
 assert(!(await s.call('t3_project_list',{})).projects.some(p=>p.workspaceRoot===root+'/.validation-t3/should-not-exist'));
 const launched=cli('launch',['--project',p.projectId,'--title','Isolated adapter validation '+variant,'--model-selection',JSON.stringify(sel)]);
 tid=launched.threadId;fs.writeFileSync(root+'/.validation-t3/'+variant+'-thread',tid);
 const conf=await s.threadConfiguration(tid); record({configuration:conf});
 assert.equal(conf.modelSelection.model,sel.model);
 if(variant==='legacy'){
  await assert.rejects(s.call('t3_thread_configure',{threadId:tid}));
  record({legacyWriterWithoutModel:'refused as required'});
 }
 cli('requests',['--thread',tid]);
 record({scenario:'catalog launch and guards',result:'pass',threadId:tid});
}finally{await s.close();}
