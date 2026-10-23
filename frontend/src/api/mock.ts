import { ApiError, terminalStates, type Task, type CreateRequest, type Decision } from './client';
export type Scenario = 'success'|'failed'|'policy-denied'|'model-invalid'|'empty-context';
let current:Task|undefined;
let started=0;
let executing=0;
let scenario:Scenario='success';
export function setScenario(value:Scenario){scenario=value;}
const copy=<T,>(value:T):T=>structuredClone(value);
export const demoApi={
  async health(){return {backend:true,tesseract:true,github_token:false,sandbox:true};},
  async create(body:CreateRequest){
    if(current&&!terminalStates.has(current.state))throw new ApiError('TASK_IN_PROGRESS','A task is already running.',false);
    started=Date.now();executing=0;
    current={schema_version:'1.0',task_id:crypto.randomUUID(),state:'queued',command:body.command,created_at:new Date().toISOString(),updated_at:new Date().toISOString(),context:null,analysis:null,action_results:[],error:null};
    return {task_id:current.task_id};
  },
  async get(id:string,_signal?:AbortSignal){
    if(!current||current.task_id!==id)throw new ApiError('TASK_NOT_FOUND','Demo task was not found.',false);
    if(!terminalStates.has(current.state)&&current.state!=='awaiting_approval'){
      const elapsed=Date.now()-started;
      current.state=executing?'executing':elapsed<1000?'queued':elapsed<2000?'collecting_context':elapsed<3000?'analyzing':'awaiting_approval';
      if(elapsed>=2000)current.context={has_screenshot:false,ocr_excerpt:scenario==='empty-context'?'':'TypeError: Cannot read properties of undefined (reading length)',terminal_errors:scenario==='empty-context'?[]:[{exception_type:'TypeError',message:'Cannot read properties of undefined (reading length)',file:'src/components/Results.tsx',line:18,raw_excerpt:'Results.tsx:18\n  return results.length ? <List items={results} /> : <Empty />;'}],pr_title:null,pr_files:[],warnings:scenario==='empty-context'?['TESSERACT_NOT_FOUND','No terminal context available']:['GITHUB_TOKEN_MISSING']};
      if(elapsed>=3000&&!executing){
        if(scenario==='failed'||scenario==='model-invalid'){current.state='failed';current.error={code:scenario==='failed'?'MODEL_UNAVAILABLE':'MODEL_INVALID_RESPONSE',message:scenario==='failed'?'The model service timed out. You can try again.':'The model returned an invalid response after two retries.',retryable:true};}
        else current.analysis={summary:scenario==='empty-context'?'More context is needed to diagnose this task.':'The results component renders before data is available.',root_cause:scenario==='empty-context'?'Screen and terminal context are unavailable.':'The initial results value is undefined, but the render reads its length.',explanation:'### What happened\nThe first render runs before the asynchronous request finishes. Reading `results.length` at that point throws a TypeError.\n\n### Proposed fix\nDefault the value to an empty array. This preserves the existing empty state until results arrive. Review the patch and the test command before approving.',confidence:scenario==='empty-context'?0.25:0.94,proposals:scenario==='empty-context'?[]:[{id:'proposal-1',title:'Give results a safe default',rationale:'Initialize the list before rendering so the empty state can display safely.',risk:'low',files:[{path:'src/components/Results.tsx',unified_diff:'--- a/src/components/Results.tsx\n+++ b/src/components/Results.tsx\n@@ -12,1 +12,1 @@\n-  const { results } = useSearch();\n+  const { results = [] } = useSearch();'}],commands:[['npm','test','--','--run']],policy_ok:scenario!=='policy-denied',policy_denial_reason:scenario==='policy-denied'?'COMMAND_NOT_ALLOWLISTED':null}]};
      }
      if(executing&&Date.now()-executing>=1500){current.state='completed';current.action_results=[{action_id:'demo-patch',status:'ok',duration_ms:128,stdout:'Demo only: patch simulated. No files were changed.',stderr:''},{action_id:'demo-tests',status:'ok',exit_code:0,duration_ms:540,stdout:'Demo only: 4 tests passed. No command was executed.',stderr:''}];}
      current.updated_at=new Date().toISOString();
    }
    return copy(current);
  },
  async decision(id:string,body:Decision){
    if(!current||current.task_id!==id)throw new ApiError('TASK_NOT_FOUND','Task was not found.',false);
    if(current.state!=='awaiting_approval')throw new ApiError('INVALID_STATE','Task is not awaiting approval.',false);
    const proposal=current.analysis?.proposals?.find(p=>p.id===body.proposal_id);
    if(!proposal)throw new ApiError('VALIDATION_ERROR','Unknown proposal.',false);
    if(body.decision==='approve'&&!proposal.policy_ok)throw new ApiError('POLICY_DENIED','Sandbox policy blocks this proposal.',false);
    current.state=body.decision==='reject'?'rejected':'executing';if(body.decision==='approve')executing=Date.now();
  },
  async cancel(id:string){if(!current||current.task_id!==id)throw new ApiError('TASK_NOT_FOUND','Task was not found.',false);if(terminalStates.has(current.state))throw new ApiError('INVALID_STATE','Task has already ended.',false);current.state='cancelled';},
};
