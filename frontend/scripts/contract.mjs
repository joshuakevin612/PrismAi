// Destructive only to disposable tasks created by this runner. No approval by default.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import Ajv from 'ajv';
import formats from 'ajv-formats';
const base=(process.env.API_BASE_URL||'http://localhost:8000/api').replace(/\/$/,'');
const spec=JSON.parse(readFileSync(new URL('../../fixtures/openapi.json',import.meta.url)));
const ajv=new Ajv({strict:false});formats(ajv);
ajv.addSchema({$id:'contract',components:spec.components});
const validators=Object.fromEntries(['TaskView','TaskCreatedResponse','HealthResponse'].map(n=>[n,ajv.compile({$ref:`contract#/components/schemas/${n}`})]));
validators.ErrorEnvelope=ajv.compile(JSON.parse(readFileSync(new URL('../../fixtures/error-response.schema.json',import.meta.url))));
function shape(name,value){assert(validators[name](value),`${name}: ${ajv.errorsText(validators[name].errors)}`);}
async function call(path,body,expected){const res=await fetch(base+path,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(12000)});const raw=await res.text();let data;try{data=raw?JSON.parse(raw):undefined;}catch{assert.fail(`${path}: non-JSON HTTP ${res.status}`);}if(expected)assert(expected.includes(res.status),`${path}: expected ${expected}, got ${res.status}`);if(!res.ok)shape('ErrorEnvelope',data);return {res,data};}
const terminal=new Set(['completed','rejected','failed','cancelled']);
const wait=()=>new Promise(r=>setTimeout(r,1000));
async function create(command='Contract smoke test: diagnose only; propose a harmless action.',screen=false){const {data}=await call('/tasks',{command,context:{include_screen:screen,include_terminal:false,include_processes:false}},[202]);shape('TaskCreatedResponse',data);return data.task_id;}
async function poll(id){const deadline=Date.now()+60000;while(Date.now()<deadline){const {data}=await call(`/tasks/${id}`,undefined,[200]);shape('TaskView',data);if(data.state==='awaiting_approval'||terminal.has(data.state))return data;await wait();}throw Error('Task did not reach review or a terminal state in 60 seconds');}
let pending;
try{
 const health=await call('/health',undefined,[200]);shape('HealthResponse',health.data);
 const invalid=await call('/tasks',{command:''},[422]);assert.equal(invalid.data.error.code,'VALIDATION_ERROR');
 const missing=await call('/tasks/contract-nonexistent',undefined,[404]);assert.equal(missing.data.error.code,'TASK_NOT_FOUND');
 pending=await create();
 const second=await call('/tasks',{command:'Second task'},[409]);assert.equal(second.data.error.code,'TASK_IN_PROGRESS');
 let view=await poll(pending);
 const image=await fetch(`${base}/tasks/${pending}/screenshot`,{signal:AbortSignal.timeout(12000)});
 if(view.context?.has_screenshot){assert.equal(image.status,200);assert.match(image.headers.get('content-type')||'',/^image\/png/);const bytes=new Uint8Array(await image.arrayBuffer());assert.deepEqual([...bytes.slice(0,8)],[137,80,78,71,13,10,26,10]);}
 else{assert(!image.ok,'No screenshot expected');shape('ErrorEnvelope',await image.json());}
 if(view.state==='awaiting_approval'&&view.analysis?.proposals.length){
  const blocked=view.analysis.proposals.find(p=>!p.policy_ok);
  if(blocked){const denied=await call(`/tasks/${pending}/decision`,{proposal_id:blocked.id,decision:'approve'},[422]);assert.equal(denied.data.error.code,'POLICY_DENIED');}
  await call(`/tasks/${pending}/decision`,{proposal_id:view.analysis.proposals[0].id,decision:'reject'},[200,202,204]);
  view=await poll(pending);assert.equal(view.state,'rejected');
  const wrong=await call(`/tasks/${pending}/decision`,{proposal_id:view.analysis.proposals[0].id,decision:'reject'},[409]);assert.equal(wrong.data.error.code,'INVALID_STATE');
 }else if(!terminal.has(view.state)){await call(`/tasks/${pending}/cancel`,{},[200,202,204]);}
 pending=await create();await call(`/tasks/${pending}/cancel`,{},[200,202,204]);view=await poll(pending);assert.equal(view.state,'cancelled');pending=undefined;
 if(process.argv.includes('--member2-mocks')){
  const root=await fetch(base.replace(/\/api$/,''),{signal:AbortSignal.timeout(12000)});assert.equal((await root.json()).mock_mode,true,'Failure drills require MOCK_MODE=1');
  for(const [command,code,retryable] of [['trigger-model-unavailable','MODEL_UNAVAILABLE',true],['trigger-model-invalid','MODEL_INVALID_RESPONSE',false],['trigger-context-fail','CONTEXT_FAILED',false]]){
   pending=await create(command);view=await poll(pending);assert.equal(view.state,'failed');assert.equal(view.error.code,code);assert.equal(view.error.retryable,retryable);pending=undefined;
  }
  pending=await create('trigger-policy-denied');view=await poll(pending);assert.equal(view.state,'awaiting_approval');const p=view.analysis.proposals[0];assert.equal(p.policy_ok,false);
  const denied=await call(`/tasks/${pending}/decision`,{proposal_id:p.id,decision:'approve'},[422]);assert.equal(denied.data.error.code,'POLICY_DENIED');
  await call(`/tasks/${pending}/decision`,{proposal_id:p.id,decision:'reject'},[200]);shape('TaskView',(await call(`/tasks/${pending}`,undefined,[200])).data);pending=undefined;
  pending=await create('Screenshot contract check',true);view=await poll(pending);assert.equal(view.context.has_screenshot,true);
  const screenshot=await fetch(`${base}/tasks/${pending}/screenshot`,{signal:AbortSignal.timeout(12000)});assert.equal(screenshot.status,200);assert.match(screenshot.headers.get('content-type')||'',/^image\/png/);assert.deepEqual([...new Uint8Array(await screenshot.arrayBuffer()).slice(0,8)],[137,80,78,71,13,10,26,10]);
  await call(`/tasks/${pending}/cancel`,{},[200]);pending=undefined;
  console.log('PASS: Member 2 mock drills: timeout, invalid response, context failure, policy denial, and PNG screenshot.');
 }
 console.log('PASS: all six endpoint routes checked; shapes, errors, concurrency, cancellation, and available review behavior verified. Approval execution intentionally requires a dedicated safe sandbox test.');
}finally{if(pending)await call(`/tasks/${pending}/cancel`,{}).catch(()=>{});}
