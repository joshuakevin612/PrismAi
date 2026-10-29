"""backend/task_manager.py - Task lifecycle orchestrator and state machine."""

import asyncio
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from shared.schemas import (
    ActionRequest,
    ActionResult,
    Analysis,
    ContextBundle,
    ContextRequest,
    CreateTaskRequest,
    DecisionRequest,
    PatchFile,
    Proposal,
    TaskError,
    TaskState,
    TaskView,
)
from backend.config import settings
from backend.context_budget import build_context_summary, prepare_prompt_context
from backend.model_client import ModelClient, ModelClientException
from shared.approval import sign_action
from shared.schemas import ExecutionAccess, PermissionRequest
from backend.permissions import permission_store, proposal_permissions
import perception
import perception.sandbox

logger = logging.getLogger("backend.task_manager")

TERMINAL_STATES = {"completed", "rejected", "failed", "cancelled"}


class AppException(Exception):
    def __init__(self, status_code: int, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable


class TaskManager:
    """Manages active tasks, state transitions, background processing, and single-task concurrency."""

    def __init__(self):
        self.tasks: Dict[str, TaskView] = {}
        # Stores the internal full context bundles for screenshot retrieval or deep inspection
        self.context_bundles: Dict[str, ContextBundle] = {}
        # Background task references to cancel if needed
        self.background_jobs: Dict[str, asyncio.Task] = {}
        self.cancel_events: Dict[str, threading.Event] = {}
        self.execution_jobs: set[str] = set()
        self.model_client = ModelClient()
        self.lock = asyncio.Lock()
        self.permission_events = {}
        self.used_capabilities = {}

    def prune_tasks(self, now=None):
        """Bound completed history without evicting an active execution."""
        now = now or datetime.now(timezone.utc)
        completed = sorted((t for t in self.tasks.values() if t.state in TERMINAL_STATES
            and (t.task_id not in self.background_jobs or self.background_jobs[t.task_id].done())),
            key=lambda t: t.updated_at, reverse=True)
        for index, task in enumerate(completed):
            task.task_grants = []
            self.background_jobs.pop(task.task_id, None)
            self.cancel_events.pop(task.task_id, None)
            self.used_capabilities.pop(task.task_id, None)
            expired = (now - task.updated_at).total_seconds() >= settings.TASK_TTL_SECONDS
            if expired or index >= settings.MAX_RETAINED_TASKS:
                bundle = self.context_bundles.pop(task.task_id, None)
                if bundle and bundle.screen and bundle.screen.screenshot_path:
                    from perception.artifacts import screenshots
                    screenshots.discard(Path(bundle.screen.screenshot_path))
                self.tasks.pop(task.task_id, None)

    def has_active_task(self) -> bool:
        """Returns True if any task is currently non-terminal."""
        if any(not self.background_jobs[task_id].done() for task_id in self.execution_jobs if task_id in self.background_jobs):
            return True
        for t in self.tasks.values():
            if t.state not in TERMINAL_STATES:
                return True
        return False

    async def create_task(self, req: CreateTaskRequest) -> str:
        """Creates a new task. Returns task_id.
        
        Enforces single active task rule: returns 409 TASK_IN_PROGRESS if a task is already running.
        """
        async with self.lock:
            self.prune_tasks()
            if self.has_active_task():
                raise AppException(
                    status_code=409,
                    code="TASK_IN_PROGRESS",
                    message="Another task is already in progress. Only one active task allowed at a time.",
                    retryable=False,
                )

            task_id = f"task-{uuid.uuid4().hex}"
            now = datetime.now(timezone.utc)

            task = TaskView(
                schema_version="1.0",
                task_id=task_id,
                state="queued",
                command=req.command,
                created_at=now,
                updated_at=now,
                context=None,
                analysis=None,
                action_results=[],
                error=None,
            )
            self.tasks[task_id] = task
            self.cancel_events[task_id] = threading.Event()

        # Launch async execution pipeline
        job = asyncio.create_task(self._run_task_pipeline(task_id, req.context))
        self.background_jobs[task_id] = job
        return task_id

    def get_task(self, task_id: str) -> TaskView:
        """Retrieves current TaskView or raises 404 TASK_NOT_FOUND."""
        task = self.tasks.get(task_id)
        if not task:
            raise AppException(
                status_code=404,
                code="TASK_NOT_FOUND",
                message=f"Task with id '{task_id}' not found",
                retryable=False,
            )
        task.access = permission_store.settings.model_copy()
        return task

    def get_screenshot_path(self, task_id: str) -> Optional[str]:
        """Returns the screenshot path for a task if available."""
        task = self.get_task(task_id)
        from perception.artifacts import screenshots
        screenshots.cleanup(settings.SCREENSHOT_TTL_SECONDS)
        bundle = self.context_bundles.get(task_id)
        if bundle and bundle.screen and bundle.screen.screenshot_path:
            return bundle.screen.screenshot_path
        return None

    async def cancel_task(self, task_id: str) -> TaskView:
        """Cancels a non-terminal task."""
        async with self.lock:
            task = self.get_task(task_id)
            if task.state in TERMINAL_STATES:
                raise AppException(
                    status_code=409,
                    code="INVALID_STATE",
                    message=f"Task '{task_id}' is already in terminal state '{task.state}' and cannot be cancelled",
                    retryable=False,
                )

            # Cancel background worker job if running
            job = self.background_jobs.get(task_id)
            self.cancel_events[task_id].set()
            if job and not job.done() and task_id not in self.execution_jobs:
                job.cancel()

            for request in task.permission_requests:
                if request.status == "pending":
                    request.status = "cancelled"
                    event = self.permission_events.get(request.id)
                    if event:
                        event.set()
            task.state = "cancelled"
            task.updated_at = datetime.now(timezone.utc)
        # During execution, wait for container removal/current atomic patch to
        # finish. Do not release the workspace to another task prematurely.
        if job and task_id in self.execution_jobs:
            try:
                await asyncio.wait_for(asyncio.shield(job), timeout=15)
            except asyncio.TimeoutError:
                logger.warning('Action cleanup still pending for %s', task_id)
        return task

    async def handle_decision(self, task_id: str, req: DecisionRequest) -> TaskView:
        """Applies approve/reject decision to an awaiting task."""
        async with self.lock:
            task = self.get_task(task_id)

            if task.state != "awaiting_approval":
                raise AppException(
                    status_code=409,
                    code="INVALID_STATE",
                    message=f"Task is in state '{task.state}', but decisions require 'awaiting_approval'",
                    retryable=False,
                )

            if not task.analysis or not task.analysis.proposals:
                raise AppException(
                    status_code=409,
                    code="INVALID_STATE",
                    message="Task has no proposals to decide upon",
                    retryable=False,
                )

            proposal = next((p for p in task.analysis.proposals if p.id == req.proposal_id), None)
            if not proposal:
                raise AppException(
                    status_code=404,
                    code="TASK_NOT_FOUND",
                    message=f"Proposal '{req.proposal_id}' not found in task analysis",
                    retryable=False,
                )

            if req.decision == "reject":
                task.state = "rejected"
                task.updated_at = datetime.now(timezone.utc)
                return task

            # Decision == "approve"
            if not proposal.policy_ok:
                raise AppException(
                    status_code=422,
                    code="POLICY_DENIED",
                    message=f"Proposal cannot be approved because it violates sandbox policy: {proposal.policy_denial_reason or 'Blocked by sandbox policy'}",
                    retryable=False,
                )

            # Transition to executing
            task.state = "executing"
            task.updated_at = datetime.now(timezone.utc)

        # Launch execution of the approved proposal
        self.execution_jobs.add(task_id)
        self.background_jobs[task_id] = asyncio.create_task(self._execute_proposal(task_id, proposal.model_copy(deep=True)))
        return task

    async def _transition(self, task_id: str, new_state: TaskState):
        """Helper to safely transition state and update timestamp."""
        async with self.lock:
            task = self.tasks.get(task_id)
            if task and task.state not in TERMINAL_STATES:
                task.state = new_state
                task.updated_at = datetime.now(timezone.utc)

    def allowed(self, task, capability):
        return getattr(permission_store.settings, capability) or capability in task.task_grants

    async def request_access(self, task, capabilities, reason, phase, proposal=None):
        missing = sorted(c for c in capabilities if not self.allowed(task, c))
        if not missing:
            return True
        request = PermissionRequest(id=uuid.uuid4().hex, capabilities=missing,
            reason=reason, phase=phase, proposal_id=proposal.id if proposal else None,
            commands=proposal.commands if proposal else [])
        event = asyncio.Event()
        self.permission_events[request.id] = event
        task.permission_requests.append(request)
        await self._transition(task.task_id, 'awaiting_permission')
        try:
            await event.wait()
            return request.status == 'allowed' and all(self.allowed(task, c) for c in missing)
        finally:
            self.permission_events.pop(request.id, None)

    async def handle_permission(self, task_id, request_id, decision):
        async with self.lock:
            task = self.get_task(task_id)
            request = next((r for r in task.permission_requests if r.id == request_id), None)
            if not request:
                raise AppException(404, 'REQUEST_NOT_FOUND', 'Access request not found.')
            desired = 'allowed' if decision == 'allow' else 'denied'
            if request.status == desired:
                return task
            if request.status != 'pending' or task.state in TERMINAL_STATES:
                raise AppException(409, 'INVALID_STATE', 'This access request is already resolved.')
            request.status = desired
            if decision == 'allow':
                task.task_grants = sorted(set(task.task_grants) | set(request.capabilities))
            task.updated_at = datetime.now(timezone.utc)
            event = self.permission_events.get(request.id)
            if event:
                event.set()
            return task

    async def update_access(self, capability, allowed):
        permission_store.update(capability, allowed)
        if allowed:
            for task in self.tasks.values():
                for request in task.permission_requests:
                    if request.status == 'pending' and all(self.allowed(task, c) for c in request.capabilities):
                        request.status = 'allowed'
                        event = self.permission_events.get(request.id)
                        if event:
                            event.set()
        if not allowed:
            for task in list(self.tasks.values()):
                task.task_grants = [c for c in task.task_grants if c != capability]
                used = capability in self.used_capabilities.get(task.task_id, set())
                bundle = self.context_bundles.get(task.task_id)
                if bundle:
                    if capability == 'screen':
                        if bundle.screen and bundle.screen.screenshot_path:
                            Path(bundle.screen.screenshot_path).unlink(missing_ok=True)
                        bundle.screen = None
                    elif capability == 'terminal':
                        bundle.terminal_errors = []
                    elif capability == 'processes':
                        bundle.processes = []
                    task.context = build_context_summary(bundle)
                if used:
                    task.analysis = None
                    if task.state not in TERMINAL_STATES:
                        await self.cancel_task(task.task_id)
        return permission_store.settings

    async def _run_task_pipeline(self, task_id: str, context_req: ContextRequest):
        task = self.tasks[task_id]
        try:
            await self._transition(task_id, 'planning_context')
            if context_req.auto:
                plan = await self.model_client.plan_context(task.command)
                selected = {s.source for s in plan.sources}
                reason = '; '.join(s.reason for s in plan.sources)
            else:
                selected = {s for s in ('screen', 'terminal', 'processes') if getattr(context_req, 'include_' + s)}
                reason = 'These sources are needed for this investigation.'
            attempted = set()
            for round_number in range(2):
                new = selected - attempted
                attempted.update(new)
                task.selected_sources = sorted(attempted)
                for source in sorted(new):
                    await self.request_access(task, {source}, reason, 'context')
                if self.cancel_events[task_id].is_set():
                    return
                sources = {c for c in attempted if self.allowed(task, c)}
                self.used_capabilities[task_id] = sources.copy()
                await self._transition(task_id, 'collecting_context')
                request = ContextRequest(auto=False, include_screen='screen' in sources,
                    include_terminal='terminal' in sources, include_processes='processes' in sources,
                    github=context_req.github)
                bundle = await asyncio.to_thread(perception.collect_context, request)
                if self.cancel_events[task_id].is_set():
                    return
                bundle.warnings.extend('ACCESS_DENIED_' + c.upper() for c in attempted - sources)
                self.context_bundles[task_id] = bundle
                task.context = build_context_summary(bundle)
                await self._transition(task_id, 'analyzing')
                prompt_context = prepare_prompt_context(task.command, bundle)
                prompt_context['unavailable_sources'] = sorted(attempted - sources)
                from backend.workspace_context import read_workspace_files
                from perception.container_runtime import availability
                prompt_context['workspace_files'] = await asyncio.to_thread(read_workspace_files, bundle, settings.ALLOWED_ROOT)
                prompt_context['execution'] = {'commands_isolated': await asyncio.to_thread(lambda: availability()[0]),
                    'access': permission_store.settings.model_dump(), 'task_grants': task.task_grants}
                analysis = await self.model_client.analyze(command=task.command,
                    budgeted_context=prompt_context, allowed_root=settings.ALLOWED_ROOT)
                selected = set(analysis.needed_context) - attempted
                if not selected or round_number == 1 or not context_req.auto:
                    break
                reason = analysis.context_reason or 'Additional context is needed to verify the diagnosis.'
            if task.state not in TERMINAL_STATES:
                task.analysis = analysis
                await self._transition(task_id, 'awaiting_approval' if analysis.proposals else 'completed')
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.exception('Task analysis failed: %s', task_id)
            if task.state not in TERMINAL_STATES:
                task.error = TaskError(code=exc.code if isinstance(exc, ModelClientException) else 'INTERNAL',
                    message=exc.message if isinstance(exc, ModelClientException) else 'Task analysis failed. Check the backend logs.',
                    retryable=exc.retryable if isinstance(exc, ModelClientException) else False)
                await self._transition(task_id, 'failed')

    async def _execute_proposal(self, task_id: str, proposal: Proposal):
        """Execute only the approved snapshot, with cooperative cancellation."""
        task = self.tasks[task_id]
        event = self.cancel_events[task_id]
        actions = []
        try:
            required = proposal_permissions(proposal)
            if not await self.request_access(task, required, 'This approved proposal needs additional access to execute.', 'execution', proposal):
                await self._transition(task_id, 'awaiting_approval')
                return
            if event.is_set():
                return
            await self._transition(task_id, 'executing')
            self.used_capabilities.setdefault(task_id, set()).update(required)
            access = ExecutionAccess(**{c: self.allowed(task, c) for c in ExecutionAccess.model_fields if c in required})
            for index, patch in enumerate(proposal.files):
                actions.append(ActionRequest(action_id=f'act-{proposal.id}-patch-{index}', kind='apply_patch', patch=patch,
                    working_dir=str(Path(settings.ALLOWED_ROOT).resolve()), approval_token='', access=access))
            for index, command in enumerate(proposal.commands):
                actions.append(ActionRequest(action_id=f'act-{proposal.id}-cmd-{index}', kind='run_command', command=command,
                    working_dir=str(Path(settings.ALLOWED_ROOT).resolve()), approval_token='', access=access))
            for action in actions:
                action.approval_token = sign_action(action, settings.APPROVAL_SECRET)
            # Recheck every action before making the first modification.
            for action in actions:
                if event.is_set():
                    return
                ok, reason = await asyncio.to_thread(perception.sandbox.validate_action, action, allowed_root=settings.ALLOWED_ROOT)
                if not ok:
                    task.action_results.append(ActionResult(action_id=action.action_id, status='denied',
                                                           denial_reason=reason, duration_ms=0))
                    raise RuntimeError('Action policy changed before execution')
            for action in actions:
                if event.is_set():
                    return
                result = await asyncio.to_thread(perception.sandbox.execute, action,
                    secret=settings.APPROVAL_SECRET, allowed_root=settings.ALLOWED_ROOT, cancel_event=event)
                async with self.lock:
                    task.action_results.append(result)
                    task.updated_at = datetime.now(timezone.utc)
                if event.is_set():
                    return
                if result.status != 'ok':
                    raise RuntimeError('An action failed or was denied')
            async with self.lock:
                if not event.is_set():
                    task.state = 'completed'
                    task.updated_at = datetime.now(timezone.utc)
        except asyncio.CancelledError:
            event.set()
            raise
        except Exception:
            logger.exception('Proposal execution failed: %s', task_id)
            async with self.lock:
                if task.state != 'cancelled':
                    task.state = 'failed'
                    task.error = TaskError(code='EXECUTION_FAILED',
                        message='An approved action failed or was denied. Inspect the action results.', retryable=False)
                    task.updated_at = datetime.now(timezone.utc)
        finally:
            self.execution_jobs.discard(task_id)

    async def shutdown(self):
        for event in self.permission_events.values():
            event.set()
        for event in self.cancel_events.values():
            event.set()
        for task_id, job in self.background_jobs.items():
            if task_id not in self.execution_jobs and not job.done():
                job.cancel()
        if self.background_jobs:
            await asyncio.gather(*self.background_jobs.values(), return_exceptions=True)


task_manager = TaskManager()
