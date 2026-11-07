import fs from 'node:fs';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
const root=process.cwd(),v=process.argv[2];
const token=root+'/.validation-t3/'+(v==='nightly'?'token':v+'-token');
const tid=fs.readFileSync(root+'/.validation-t3/'+v+'-thread','utf8');
const log='~/.no-mistakes/evidence/01M6TW2N0WHAV0YP4KA3JWP9YW/'+v+'-questions.jsonl';
function record(x){fs.appendFileSync(log,JSON.stringify(x)+'\n');console.log(JSON.stringify(x));}
function cli(verb,args=[],want=0){const p=spawnSync('node',['bin/fm-t3-mcp.mjs',verb,'--thread',tid,...args,'--token-file',token],{encoding:'utf8',timeout:60000});record({verb,args,exit:p.status,output:p.stdout.trim(),stderr:p.stderr.trim()});assert.equal(p.status,want);return JSON.parse(p.stdout);}
const message=root+'/.validation-t3/'+v+'-message';
fs.writeFileSync(message,'This is a disposable integration test. Do not read or write files. Do not run commands. Use your AskUserQuestion tool now to ask: Which validation colour? Offer Blue and Green as options, with single selection. Wait for the answer. Then reply with exactly VALIDATION_COLOUR=<chosen colour>.');
cli('send',['--message-file',message,'--client-request-id','question-validation-'+v]);
let q;
for(let i=0;i<45;i++){
 const out=cli('requests'); if(out.questions.length){q=out.questions[0];break;}
 await new Promise(r=>setTimeout(r,2000));
}
assert(q,'No live question reached pending state');
const question=q.questions[0];
const answer=root+'/.validation-t3/'+v+'-answers';fs.writeFileSync(answer,JSON.stringify({[question.id]:'Blue'}));
cli('respond',['--request','missing-validation-request','--answers-file',answer],3);
cli('respond',['--request',q.requestId,'--answers-file',answer]);
const waited=cli('wait',['--timeout-ms','45000']);record({completedRun:waited});
const out=cli('read',['--limit','30']);
assert(JSON.stringify(out).includes('VALIDATION_COLOUR=Blue'),'The agent did not receive the chosen answer');
assert.equal(cli('requests').questions.length,0);
cli('archive',['--timeout-ms','15000']);
record({scenario:'live question list read respond and refusal',result:'pass'});
