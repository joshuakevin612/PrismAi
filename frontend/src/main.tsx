import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowUpRight, Check, ChevronRight, FileCode2, GitPullRequest, LoaderCircle, Play, Plus, Settings2, ShieldCheck, Square, Terminal, X } from 'lucide-react';
import Markdown from 'react-markdown';
import { ApiError, base, liveApi, terminalStates, type Task, type CreateRequest, type Decision, request } from './api/client';
import type { components } from './api/types';
type Access=components['schemas']['AccessSettings'];
type Capability=components['schemas']['AccessUpdate']['capability'];
const names:Record<Capability,string>={screen:'Screen',terminal:'Terminal',processes:'Processes',modify_files:'Modify files',install_dependencies:'Install dependencies',network:'Command network'};
import './style.css';
import { Intro, PrismMark, Surface, ThemeToggle } from './Experience';
import { WorkspaceCat } from './WorkspaceCat';
const labels:Record<Task['state'],string>={queued:'Queued',planning_context:'Choosing context',awaiting_permission:'Waiting for access',collecting_context:'Collecting context',analyzing:'Analyzing',awaiting_approval:'Needs your approval',executing:'Executing',completed:'Completed',failed:'Failed',cancelled:'Cancelled',rejected:'Rejected'};
const steps=['queued','collecting_context','analyzing','awaiting_approval','executing','completed'];
function savedTask():string|null { try { return localStorage.getItem('prism-active-task'); } catch { return null; } }
function rememberTask(id:string|null) { try { if(id)localStorage.setItem('prism-active-task',id);else localStorage.removeItem('prism-active-task'); } catch { /* Task state still works in memory. */ } }
function App(){
 const api=liveApi;
 const [access,setAccess]=useState<Access|null>(null),[popup,setPopup]=useState(false),[accessBusy,setAccessBusy]=useState(false);
 const [accessError,setAccessError]=useState('');
 const commandRef=useRef<HTMLTextAreaElement>(null);
 const seenRequest=useRef('');
 const permissionRef=useRef<HTMLDivElement>(null);
 const reopenRef=useRef<HTMLButtonElement>(null);
 const [task,setTask]=useState<Task|null>(null),[history,setHistory]=useState<Task[]>([]),[command,setCommand]=useState(''),[repo,setRepo]=useState(''),[pr,setPr]=useState('');
 const [busy,setBusy]=useState(false),[error,setError]=useState<ApiError|null>(null),[health,setHealth]=useState('Checking connection'),[pollVersion,setPollVersion]=useState(0),[imageFailed,setImageFailed]=useState(false);
 const [readiness,setReadiness]=useState<string[]>([]);
 const retry=useRef<(()=>void)|null>(null);
 const active=!!task&&!terminalStates.has(task.state);
 function fail(err:unknown,action:()=>void){setError(err instanceof ApiError?err:new ApiError('UNEXPECTED_ERROR',err instanceof Error?err.message:'Something went wrong.',true));retry.current=action;}
 useEffect(()=>{let mounted=true;api.health().then(result=>{if(!mounted)return;setHealth('Live backend connected');setReadiness([...(result.m1?.model_configured?[]:['Configure NVIDIA_API_KEY in the backend .env file.']),...(result.m1?.sandbox?[]:['Start Docker Desktop to execute commands.']),...(result.m1?.tesseract?[]:['Screen text recognition is unavailable. Screenshots can still be captured.'])]);}).catch(()=>mounted&&setHealth('Backend offline'));
 request<Access>('/access').then(value=>mounted&&setAccess(value)).catch(err=>mounted&&setAccessError(err.message));
 const saved=savedTask();if(saved)api.get(saved).then(value=>mounted&&setTask(value)).catch(()=>rememberTask(null));
 return()=>{mounted=false;};},[]);
 const pending=task?.permission_requests?.find(r=>r.status==='pending');
 useEffect(()=>{if(pending&&pending.id!==seenRequest.current){seenRequest.current=pending.id;setPopup(true);}if(!pending)setPopup(false);},[pending?.id]);
 useEffect(()=>{if(popup)permissionRef.current?.focus();else if(pending)reopenRef.current?.focus();},[popup]);
 useEffect(()=>{if(task){rememberTask(task.task_id);if(task.access)setAccess(task.access);}},[task]);
 async function toggle(capability:Capability,allowed:boolean){setAccessBusy(true);try{setAccess(await request<Access>('/access',{capability,allowed}));if(task)setTask(await api.get(task.task_id));}catch(err){fail(err,()=>void toggle(capability,allowed));}finally{setAccessBusy(false);}}
 async function permit(decision:'allow'|'deny'){if(!task||!pending)return;setAccessBusy(true);try{setTask(await request<Task>(`/tasks/${task.task_id}/permissions/${pending.id}`,{decision}));setPopup(false);}catch(err){fail(err,()=>void permit(decision));}finally{setAccessBusy(false);}}
 useEffect(()=>{
   if(!task||terminalStates.has(task.state))return;
   let disposed=false;let timer:ReturnType<typeof setTimeout>;const controller=new AbortController();
   async function poll(){try{const next=await api.get(task!.task_id,controller.signal);if(disposed)return;setTask(next);if(!terminalStates.has(next.state))timer=setTimeout(poll,1000);}catch(err){if(!disposed)fail(err,()=>{setError(null);setPollVersion(v=>v+1);});}}
   timer=setTimeout(poll,1000);return()=>{disposed=true;clearTimeout(timer);controller.abort();};
 },[task?.task_id,task?.state,pollVersion]);
 useEffect(()=>{if(task&&terminalStates.has(task.state))setHistory(items=>[task,...items.filter(t=>t.task_id!==task.task_id)].slice(0,8));},[task]);
 async function submit(override?:string){
   if(busy||active||(!override&&!valid)||!validPR)return;setBusy(true);setError(null);setImageFailed(false);
   const body:CreateRequest={command:(override??command).trim(),context:{auto:true,include_screen:false,include_terminal:false,include_processes:false,...(repo.trim()?{github:{repo:repo.trim(),pr_number:Number(pr)}}:{})}};
   try{const created=await api.create(body);const now=new Date().toISOString();setTask({schema_version:'1.0',task_id:created.task_id,state:'queued',command:body.command,created_at:now,updated_at:now,action_results:[]});}catch(err){fail(err,()=>void submit(body.command));}finally{setBusy(false);}
 }
 async function act(body?:Decision){if(!task||busy)return;setBusy(true);setError(null);try{if(body)await api.decision(task.task_id,body);else await api.cancel(task.task_id);setTask(await api.get(task.task_id));}catch(err){fail(err,()=>void act(body));}finally{setBusy(false);}}
 const validPR=!repo.trim()||(/^[^/\s]+\/[^/\s]+$/.test(repo.trim())&&Number.isSafeInteger(Number(pr))&&Number(pr)>0);
 const valid=!!command.trim()&&command.length<=2000&&validPR;
 const index=task?steps.indexOf(task.state==='planning_context'?'collecting_context':task.state==='awaiting_permission'?(pending?.phase==='execution'?'awaiting_approval':'collecting_context'):task.state):-1;

 useEffect(()=>setImageFailed(false),[task?.task_id]);
 function newTask(){
   if(active)return;
   setTask(null);rememberTask(null);setError(null);setCommand('');
   commandRef.current?.focus();
 }
 function example(value:string){setCommand(value);commandRef.current?.focus();}
 async function reloadAccess(){
   setAccessError('');setAccessBusy(true);
   try{setAccess(await request<Access>('/access'));}catch(err){setAccessError(err instanceof Error?err.message:'Could not load access settings.');}
   finally{setAccessBusy(false);}
 }
 const automatic=access?Object.values(access).filter(value=>value===true).length:0;
 const historyItems=history.map(t=><button className="history-item" key={t.task_id} disabled={active} aria-current={task?.task_id===t.task_id} onClick={()=>{setTask(t);setError(null);}}><span className={`dot ${t.state}`}/><span>{t.command}</span></button>);

 return <Intro><div className="shell workspace-reveal" id="workspace" tabIndex={-1}>
  <aside className="rail" aria-label="Task navigation">
   <a className="brand" href="#workspace" aria-label="Prism workspace"><PrismMark/><span>prism.</span></a>
   <div className="rail-body">
    <button className="new-task" disabled={active} onClick={newTask}>New investigation<Plus size={16}/></button>
    <div className="history-title"><span>This session</span><span>{history.length}</span></div>
    {history.length===0?<p className="rail-hint">Your completed investigations will appear here.</p>:historyItems}
   </div>
   <div className="rail-footer"><ShieldCheck size={16}/><p>Every execution<br/>starts with your approval.</p></div>
  </aside>
  <div className="body">
   <header className="topbar">
    <span className="topbar-title">Task workspace</span>
    <a className="brand mobile-brand" href="#workspace" aria-label="Prism workspace"><PrismMark/><span>prism.</span></a>
    <div className="topbar-tools">
     <span className="connection" role="status"><span className={`dot ${health==='Backend offline'?'failed':health==='Live backend connected'?'completed':''}`}/>{health==='Live backend connected'?'Backend connected':health}</span>
     <ThemeToggle/>
    </div>
   </header>
   <main id="investigation" tabIndex={-1}><WorkspaceCat/>
    <div className="welcome">
     <div><h2>Let’s look into it.</h2><p>Describe the problem. Review the next step.</p></div><div className="back-to-top-group"><a className="back-to-top" href="#top">Back to top <ArrowUpRight size={14}/></a><small className="sriren-note">A little break? Pet Sriren.</small></div>
    </div>
    <div className="workspace">
     <div className="main-column">
      <form className="composer" onSubmit={e=>{e.preventDefault();void submit();}}>
       <label htmlFor="command">What are we working on?</label>
       <textarea ref={commandRef} id="command" maxLength={2000} aria-describedby="composer-note" placeholder="Describe an error, ask about a pull request, or investigate your screen…" value={command} onChange={e=>setCommand(e.target.value)} disabled={active||busy}/>
       <div className="composer-footer"><span>{command.length} / 2000</span><button className="primary" disabled={!valid||active||busy} type="submit">{busy?<LoaderCircle className="spin" size={16}/>:<ArrowUpRight size={17}/>}Analyze task</button></div>
      </form>
      <p className="composer-note" id="composer-note"><ShieldCheck size={14}/>You review every patch and command before it runs.</p>
      {!task&&<div className="empty">
       <p>Need a starting point?</p>
       <button className="example" onClick={()=>example('Find out why my results component crashes and propose a fix.')}><Terminal size={15}/><span>Investigate a component crash</span><ArrowUpRight size={14}/></button>
       <button className="example" onClick={()=>example('Diagnose the latest terminal error and propose a minimal fix.')}><FileCode2 size={15}/><span>Explain my latest terminal error</span><ArrowUpRight size={14}/></button>
      </div>}
      {task&&terminalStates.has(task.state)&&<button className="mobile-new-task" onClick={newTask}><Plus size={15}/>New investigation</button>}
 {error&&<div role="alert" className="error"><strong>{error.code}</strong><p>{error.message}</p>{error.retryable&&<button onClick={()=>{setError(null);retry.current?.();}}>Retry request</button>}</div>}
 {task&&<Surface key={task.task_id}><section className="task"><div className="section-heading"><h2>Task investigation</h2><span className={`status ${task.state}`} aria-live="polite">{labels[task.state]}</span></div><p className="task-command">{task.command}</p>{!['failed','cancelled','rejected'].includes(task.state)&&<div className="timeline" aria-label="Task progress">{steps.map((s,i)=><div className={i<=index?'reached':''} key={s}><span>{i<index?<Check size={12}/>:i+1}</span><small>{['Queued','Context','Analysis','Review','Execute','Done'][i]}</small></div>)}</div>}<div className="task-meta"><code>{task.task_id.slice(0,8)}</code><span>Started {new Date(task.created_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</span>{active&&<button disabled={busy} onClick={()=>void act()}><Square size={12}/>Cancel task</button>}</div>
 {active&&!task.analysis&&<p className="working" aria-live="polite"><LoaderCircle className="spin" size={17}/>{labels[task.state]}…</p>}
 {task.error&&<div className="error" role="alert"><strong>{task.error.code}</strong><p>{task.error.message}</p>{task.error.retryable&&<button disabled={busy} onClick={()=>{setCommand(task.command);void submit(task.command);}}>Retry task</button>}</div>}
 {task.analysis&&<><div className="analysis"><div className="section-heading"><h3>{task.analysis.summary}</h3><span className="confidence">{Math.round(task.analysis.confidence*100)}% confidence</span></div><h4>Root cause</h4><p>{task.analysis.root_cause}</p><Markdown>{task.analysis.explanation}</Markdown></div><div className="section-heading"><h3>Proposed actions</h3><span>{(task.analysis.proposals??[]).length} proposal{(task.analysis.proposals??[]).length!==1?'s':''}</span></div>{(task.analysis.proposals??[]).length===0&&<p>No actions were proposed. Add context and start a new task.</p>}{(task.analysis.proposals??[]).map(p=><article className="proposal" key={p.id}><div className="section-heading"><h3>{p.title}</h3><span className={`risk ${p.risk}`}>{p.risk} risk</span></div><p>{p.rationale}</p>{(p.files??[]).map((f,i)=><details open key={`${f.path}-${i}`} className="diff"><summary><FileCode2 size={15}/>{f.path}</summary><pre>{f.unified_diff.split('\n').map((line,i)=><span key={i} className={line.startsWith('+')?'added':line.startsWith('-')?'removed':''}>{line}{'\n'}</span>)}</pre></details>)}{(p.commands??[]).length>0&&<div className="commands"><h4>Commands to run</h4>{p.commands?.map((cmd,i)=><pre key={i}>{JSON.stringify(cmd)}</pre>)}</div>}<p className="required-access">Required access: {p.required_permissions?.map(c=>names[c]).join(', ')||'Read-only workspace · no command network'}</p><div className={`policy ${p.policy_ok?'allowed':'denied'}`}><ShieldCheck size={17}/>{p.policy_ok?'Sandbox policy check passed':`Blocked by policy: ${p.policy_denial_reason||'POLICY_DENIED'}`}</div>{task.state==='awaiting_approval'&&<div className="decision"><span>Review the patch and commands. Extra access is requested before execution.</span><button disabled={busy} onClick={()=>void act({proposal_id:p.id,decision:'reject'})}><X size={15}/>Reject</button><button className="primary" disabled={busy||!p.policy_ok} onClick={()=>void act({proposal_id:p.id,decision:'approve'})}><Play size={14}/>Approve proposal</button></div>}</article>)}</>}
 {(task.action_results??[]).length>0&&<section className="results"><h3>Execution results</h3>{task.action_results?.map(r=><div key={r.action_id}><div className="section-heading"><strong>{r.action_id}</strong><span>{r.status} · {r.duration_ms} ms{r.exit_code!=null?` · exit ${r.exit_code}`:''}</span></div>{r.denial_reason&&<p className="error">{r.denial_reason}</p>}{r.stdout&&<pre>{r.stdout}</pre>}{r.stderr&&<pre className="stderr">{r.stderr}</pre>}</div>)}</section>}
 {terminalStates.has(task.state)&&<div className="task-end" role="status">{task.state==='completed'?<Check size={17}/>:<Square size={17}/>}<span>Task {labels[task.state].toLowerCase()}. You can start another investigation above.</span></div>}</section></Surface>}

     </div>
     <aside className="context-column" aria-label="Context and settings">
      <details className="settings-group">
       <summary><Settings2 size={17}/><span>Access & permissions<small>{access?`${automatic} automatic · ${6-automatic} ask first`:'Settings unavailable'}</small></span><ChevronRight className="disclosure-arrow"/></summary>
       <div className="settings-content">
        <p>Choose what Prism can access automatically. Everything else asks first.</p>
        {accessError&&<p role="status">{accessError} <button disabled={accessBusy} onClick={()=>void reloadAccess()}>Retry settings</button></p>}
        {(['screen','terminal','processes','modify_files','install_dependencies','network'] as Capability[]).map(capability=><div className="source" key={capability}>
         <label><span><strong>{names[capability]}</strong><small>{access?.[capability]?'Allowed automatically':'Ask when needed'}{task?.task_grants?.includes(capability)?' · this task allowed':''}</small></span>
          <input aria-label={`Allow ${names[capability]} automatically`} type="checkbox" role="switch" checked={access?.[capability]??false} disabled={!access||accessBusy} onChange={e=>void toggle(capability,e.target.checked)}/>
         </label>
         {task?.task_grants?.includes(capability)&&<button type="button" disabled={accessBusy} onClick={()=>void toggle(capability,false)}>Revoke</button>}
        </div>)}
        <p className="access-scope">Network access applies to Docker commands. NVIDIA and an attached GitHub PR use their configured APIs. Revoking access stops a task using it.</p>
       </div>
      </details>
      <details className="settings-group github">
       <summary><GitPullRequest size={17}/><span>Pull request<small>{repo&&validPR?`${repo} #${pr}`:'Attach a GitHub PR'}</small></span><ChevronRight className="disclosure-arrow"/></summary>
       <div className="settings-content">
        <label>Repository<input placeholder="owner/repository" value={repo} disabled={active||busy} onChange={e=>setRepo(e.target.value)} autoCapitalize="none" spellCheck={false} aria-invalid={!!repo&&!validPR} aria-describedby={!validPR?'pr-error':undefined}/></label>
        <label>PR number<input type="number" min="1" step="1" placeholder="123" value={pr} aria-invalid={!validPR} disabled={active||busy} onChange={e=>setPr(e.target.value)} aria-describedby={!validPR?'pr-error':undefined}/></label>
        {!validPR&&<small id="pr-error" role="status">Enter owner/repository and a positive PR number.</small>}
       </div>
      </details>
      {readiness.length>0&&<details className="settings-group readiness">
       <summary><Terminal size={17}/><span>Environment<small>{readiness.length} setup {readiness.length===1?'notice':'notices'}</small></span><ChevronRight className="disclosure-arrow"/></summary>
       <div className="settings-content">{readiness.map(message=><p key={message}>{message}</p>)}</div>
      </details>}
      {task&&<p className="selected-sources">Selected context: {task.selected_sources?.map(c=>names[c]).join(', ')||(active?'Choosing context…':'None collected')}</p>}
 {task?.context&&<section className="collected"><h2>Captured context</h2>{task.context.warnings?.map((w,i)=><p className="warning" key={i}>{w}</p>)}{task.context.has_screenshot&&(imageFailed?<p>Screenshot could not be loaded.</p>:<a href={`${base}/tasks/${encodeURIComponent(task.task_id)}/screenshot`} target="_blank" rel="noreferrer"><img alt="Captured screen" src={`${base}/tasks/${encodeURIComponent(task.task_id)}/screenshot`} onError={()=>setImageFailed(true)}/></a>)}{task.context.ocr_excerpt&&<details><summary>Screen text</summary><pre>{task.context.ocr_excerpt}</pre></details>}{(task.context.terminal_errors??[]).map((e,i)=><div className="terminal-error" key={i}><strong>{e.exception_type||'Terminal error'}</strong><p>{e.message}</p><code>{e.file}{e.line?`:${e.line}`:''}</code><pre>{e.raw_excerpt}</pre></div>)}{task.context.pr_title&&<h3>{task.context.pr_title}</h3>}{task.context.pr_files?.map(f=><p key={f}><code>{f}</code></p>)}</section>}

      <details className="context-help"><summary>How does Prism work?<ChevronRight className="disclosure-arrow"/></summary><p>Prism selects relevant context, explains the problem, and proposes patches and commands. You review the exact changes and approve execution. Commands run in Docker.</p></details>
     </aside>
    </div>
    {history.length>0&&<details className="mobile-history"><summary>This session · {history.length} investigation{history.length===1?'':'s'}<ChevronRight className="disclosure-arrow"/></summary>{historyItems}</details>}
    <footer><span>Local context. Your call.</span><span>Prism</span></footer>
   </main>
  </div>
 </div>
  {pending&&<button ref={reopenRef} className="access-reopen" onClick={()=>setPopup(true)}><ShieldCheck size={17}/>Access request · {pending.capabilities.map(c=>names[c]).join(', ')}</button>}
  {popup&&pending&&<div className="permission-popup" role="dialog" aria-modal="false" aria-labelledby="permission-title" tabIndex={-1} ref={permissionRef} onKeyDown={e=>{if(e.key==='Escape')setPopup(false);}}>
   <Surface><div className="section-heading"><h2 id="permission-title">Allow access?</h2><div><button aria-label="Minimize access request" onClick={()=>setPopup(false)}>−</button><button aria-label="Close access request" onClick={()=>setPopup(false)}><X size={17}/></button></div></div>
   <p>{pending.reason}</p><ul>{pending.capabilities.map(c=><li key={c}>{names[c]}</li>)}</ul>
   {(pending.commands??[]).map((cmd,i)=><pre key={i}>{JSON.stringify(cmd)}</pre>)}
   <small>For this task only. Closing this panel keeps the request pending.</small>
   <div className="permission-actions"><button disabled={accessBusy} onClick={()=>void permit('deny')}>Deny access</button><button className="primary" disabled={accessBusy} onClick={()=>void permit('allow')}>Allow for this task</button></div></Surface>
  </div>}
 </Intro>;
}
const root = import.meta.hot?.data.root ?? createRoot(document.getElementById('root')!);
if (import.meta.hot) import.meta.hot.data.root = root;
root.render(<React.StrictMode><App/></React.StrictMode>);

