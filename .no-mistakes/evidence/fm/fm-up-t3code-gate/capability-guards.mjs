import http from 'node:http';
import fs from 'node:fs';
import {spawn} from 'node:child_process';
import assert from 'node:assert/strict';
const root=process.cwd(),c=JSON.parse(fs.readFileSync(root+'/.validation-t3/token'));
const evidence='~/.no-mistakes/evidence/01M6TW2N0WHAV0YP4KA3JWP9YW/capability-guards.jsonl';
let omitted,mutationCalls=[];
const server=http.createServer(async(req,res)=>{
 try{
  let data='';for await(const chunk of req)data+=chunk;
  const msg=data?JSON.parse(data):null;
  if(msg?.method==='tools/call'&&!['t3_environment_read'].includes(msg.params.name))mutationCalls.push(msg.params.name);
  const headers={...req.headers,host:'127.0.0.1:43773'};delete headers.connection;delete headers['content-length'];
  const upstream=await fetch(c.origin+req.url,{method:req.method,headers,...(data?{body:data}:{})});
  let text=await upstream.text();
  if(msg?.method==='tools/list'){
   const result=JSON.parse(text);result.result.tools=result.result.tools.filter(t=>!omitted.includes(t.name));text=JSON.stringify(result);
  }
  res.writeHead(upstream.status,{'content-type':upstream.headers.get('content-type')||'application/json',...(upstream.headers.get('mcp-session-id')?{'mcp-session-id':upstream.headers.get('mcp-session-id')}:{})});res.end(text);
 }catch(e){res.writeHead(500);res.end(e.message);}
});
await new Promise(r=>server.listen(43776,'127.0.0.1',r));
const token=root+'/.validation-t3/proxy-token';fs.writeFileSync(token,JSON.stringify({...c,origin:'http://127.0.0.1:43776'}),{mode:0o600});
try{
 for(omitted of [['t3_pending_request'],['t3_thread_configure']]){
  mutationCalls=[];
  const args=['bin/fm-t3-mcp.mjs','launch','--project','absent','--title','must refuse','--model-selection','{"instanceId":"claudeAgent","model":"claude-haiku-5-5"}','--token-file',token];
  const child=spawn('node',args);let out='',err='';child.stdout.on('data',d=>out+=d);child.stderr.on('data',d=>err+=d);
  const exit=await new Promise(r=>child.on('close',r));
  fs.appendFileSync(evidence,JSON.stringify({setup:'Real T3 nightly server behind loopback proxy that only removes named tools from tools/list',omitted,exit,output:out.trim(),stderr:err.trim(),forwardedToolCalls:mutationCalls})+'\n');
  assert.equal(exit,4);assert.equal(JSON.parse(out).error.code,'capability_gate');assert.deepEqual(mutationCalls,[]);
 }
}finally{await new Promise(r=>server.close(r));}
