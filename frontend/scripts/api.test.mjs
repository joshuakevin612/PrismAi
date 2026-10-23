import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
function compile(source){return 'data:text/javascript;base64,'+Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString('base64');}
const clientURL=compile(readFileSync(new URL('../src/api/client.ts',import.meta.url),'utf8').replaceAll('import.meta.env.VITE_API_BASE_URL',"''"));
const client=await import(clientURL);
const mock=await import(compile(readFileSync(new URL('../src/api/mock.ts',import.meta.url),'utf8').replace("'./client'",JSON.stringify(clientURL))));
test('client distinguishes network, non-JSON, envelope, and empty success responses',async()=>{
 const original=globalThis.fetch;
 try{
  globalThis.fetch=async()=>{throw new TypeError('offline');};
  await assert.rejects(client.request('/health'),e=>e.code==='NETWORK_ERROR'&&e.retryable);
  globalThis.fetch=async()=>new Response('<html>bad gateway</html>',{status:502});
  await assert.rejects(client.request('/health'),e=>e.code==='INVALID_RESPONSE'&&e.retryable);
  globalThis.fetch=async()=>Response.json({error:{code:'POLICY_DENIED',message:'Blocked',retryable:false}},{status:422});
  await assert.rejects(client.request('/tasks/a/decision',{}),e=>e.code==='POLICY_DENIED'&&!e.retryable);
  globalThis.fetch=async()=>new Response(null,{status:204});assert.equal(await client.request('/tasks/a/cancel',{}),undefined);
 }finally{globalThis.fetch=original;}
});
test('demo enforces concurrency, approval policy, and terminal state transitions',async()=>{
 const original=Date.now;let now=100000;Date.now=()=>now;
 try{
  for(const scenario of ['success','failed','policy-denied','model-invalid','empty-context']){
   mock.setScenario(scenario);const {task_id:id}=await mock.demoApi.create({command:'test'});
   await assert.rejects(mock.demoApi.create({command:'overlap'}),e=>e.code==='TASK_IN_PROGRESS');
   await assert.rejects(mock.demoApi.decision(id,{proposal_id:'proposal-1',decision:'approve'}),e=>e.code==='INVALID_STATE');
   now+=1100;assert.equal((await mock.demoApi.get(id)).state,'collecting_context');
   now+=1000;assert.equal((await mock.demoApi.get(id)).state,'analyzing');
   now+=1000;let view=await mock.demoApi.get(id);
   if(scenario==='failed'||scenario==='model-invalid'){assert.equal(view.state,'failed');assert(view.error);continue;}
   assert.equal(view.state,'awaiting_approval');
   if(scenario==='success'){await mock.demoApi.decision(id,{proposal_id:'proposal-1',decision:'approve'});now+=1600;view=await mock.demoApi.get(id);assert.equal(view.state,'completed');assert.equal(view.action_results.length,2);}
   else if(scenario==='policy-denied'){await assert.rejects(mock.demoApi.decision(id,{proposal_id:'proposal-1',decision:'approve'}),e=>e.code==='POLICY_DENIED');await mock.demoApi.decision(id,{proposal_id:'proposal-1',decision:'reject'});assert.equal((await mock.demoApi.get(id)).state,'rejected');}
   else{assert.equal(view.analysis.proposals.length,0);await mock.demoApi.cancel(id);assert.equal((await mock.demoApi.get(id)).state,'cancelled');}
  }
 }finally{Date.now=original;}
});
