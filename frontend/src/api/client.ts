import type { components } from './types';
export type Task = components['schemas']['TaskView'];
export type CreateRequest = components['schemas']['CreateTaskRequest'];
export type Decision = components['schemas']['DecisionRequest'];
export type Health = components['schemas']['HealthResponse'];
export const terminalStates = new Set<Task['state']>(['completed','rejected','failed','cancelled']);
export class ApiError extends Error {
  constructor(public code: string, message: string, public retryable: boolean) {super(message);}
}
export const base = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/,'');
export async function request<T>(path:string, body?:unknown, signal?:AbortSignal):Promise<T> {
  let response:Response;
  try {response=await fetch(`${base}${path}`,{method:body===undefined?'GET':'POST',headers:body===undefined?{}:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body),signal});}
  catch(error) {if(signal?.aborted)throw error;throw new ApiError('NETWORK_ERROR','Cannot reach the backend. Check that it is running on port 8000.',true);}
  const raw=await response.text();
  let data:unknown;
  try {data=raw?JSON.parse(raw):undefined;} catch {throw new ApiError('INVALID_RESPONSE',`The backend returned a non-JSON response (HTTP ${response.status}).`,true);}
  if(!response.ok) {
    const envelope=data as {error?:{code?:string;message?:string;retryable?:boolean}};
    throw new ApiError(envelope?.error?.code||'HTTP_ERROR',envelope?.error?.message||`Request failed (HTTP ${response.status}).`,envelope?.error?.retryable??response.status>=500);
  }
  return data as T;
}
export const liveApi={create:(body:CreateRequest)=>request<{task_id:string}>('/tasks',body),get:(id:string,signal?:AbortSignal)=>request<Task>(`/tasks/${encodeURIComponent(id)}`,undefined,signal),decision:(id:string,body:Decision)=>request<unknown>(`/tasks/${encodeURIComponent(id)}/decision`,body),cancel:(id:string)=>request<unknown>(`/tasks/${encodeURIComponent(id)}/cancel`,{}),health:()=>request<Health>('/health')};
