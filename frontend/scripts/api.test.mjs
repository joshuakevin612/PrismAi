import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
function compile(source){return 'data:text/javascript;base64,'+Buffer.from(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText).toString('base64');}
const clientURL=compile(readFileSync(new URL('../src/api/client.ts',import.meta.url),'utf8').replaceAll('import.meta.env.VITE_API_BASE_URL',"''"));
const client=await import(clientURL);
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
test('permission requests use POST and preserve exact decisions',async()=>{
 const original=globalThis.fetch;
 try{let received;globalThis.fetch=async(url,options)=>{received={url,...options};return Response.json({state:'awaiting_permission'});};
 const result=await client.request('/tasks/task-a/permissions/request-a',{decision:'deny'});
 assert.equal(received.method,'POST');assert.deepEqual(JSON.parse(received.body),{decision:'deny'});assert.equal(result.state,'awaiting_permission');
 }finally{globalThis.fetch=original;}
});
