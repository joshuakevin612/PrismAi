"""backend/task_manager.py - Task lifecycle orchestrator and state machine."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
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
from backend.security import generate_approval_token
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
        self.model_client = ModelClient()
        self.lock = asyncio.Lock()

    def has_active_task(self) -> bool:
        """Returns True if any task is currently non-terminal."""
        for t in self.tasks.values():
            if t.state not in TERMINAL_STATES:
                return True
        return False

    async def create_task(self, req: CreateTaskRequest) -> str:
        """Creates a new task. Returns task_id.
        
        Enforces single active task rule: returns 409 TASK_IN_PROGRESS if a task is already running.
        """
        async with self.lock:
            if self.has_active_task():
                raise AppException(
                    status_code=409,
                    code="TASK_IN_PROGRESS",
                    message="Another task is already in progress. Only one active task allowed at a time.",
                    retryable=False,
                )

            task_id = f"task-{uuid.uuid4().hex[:8]}"
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
        return task

    def get_screenshot_path(self, task_id: str) -> Optional[str]:
        """Returns the screenshot path for a task if available."""
        task = self.get_task(task_id)
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
            if job and not job.done():
                job.cancel()

            task.state = "cancelled"
            task.updated_at = datetime.now(timezone.utc)
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
        asyncio.create_task(self._execute_proposal(task_id, proposal))
        return task

    async def _transition(self, task_id: str, new_state: TaskState):
        """Helper to safely transition state and update timestamp."""
        async with self.lock:
            task = self.tasks.get(task_id)
            if task and task.state not in TERMINAL_STATES:
                task.state = new_state
                task.updated_at = datetime.now(timezone.utc)

    async def _run_task_pipeline(self, task_id: str, context_req: ContextRequest):
        """Asynchronous execution pipeline walking through the state machine."""
        try:
            task = self.tasks[task_id]
            cmd_lower = task.command.lower()

            # 1. State: queued -> collecting_context
            if settings.MOCK_MODE:
                await asyncio.sleep(1.0)
            await self._transition(task_id, "collecting_context")

            # Drill scenario: Fail at collection
            if "trigger-context-fail" in cmd_lower or "context_failed" in cmd_lower:
                async with self.lock:
                    task.state = "failed"
                    task.error = TaskError(
                        code="CONTEXT_FAILED",
                        message="Simulated M1 perception collection catastrophic failure",
                        retryable=False,
                    )
                    task.updated_at = datetime.now(timezone.utc)
                return

            # Collect context from perception module (M1)
            try:
                bundle = perception.collect_context(context_req)
                self.context_bundles[task_id] = bundle
                summary = build_context_summary(bundle)
                async with self.lock:
                    task.context = summary
                    task.updated_at = datetime.now(timezone.utc)
            except Exception as exc:
                logger.exception("Context collection raised an unexpected exception")
                async with self.lock:
                    task.state = "failed"
                    task.error = TaskError(
                        code="CONTEXT_FAILED",
                        message=f"M1 context collection failed: {exc}",
                        retryable=False,
                    )
                    task.updated_at = datetime.now(timezone.utc)
                return

            # 2. State: collecting_context -> analyzing
            if settings.MOCK_MODE:
                await asyncio.sleep(1.0)
            await self._transition(task_id, "analyzing")

            # Prepare budgeted context dictionary
            prompt_context = prepare_prompt_context(task.command, bundle)

            # Call model client (handles retry loop & validation)
            try:
                analysis = await self.model_client.analyze(
                    command=task.command,
                    budgeted_context=prompt_context,
                    allowed_root=settings.ALLOWED_ROOT,
                )
            except ModelClientException as mce:
                async with self.lock:
                    task.state = "failed"
                    task.error = TaskError(
                        code=mce.code,
                        message=mce.message,
                        retryable=mce.retryable,
                    )
                    task.updated_at = datetime.now(timezone.utc)
                return
            except Exception as exc:
                logger.exception("Unexpected error in analysis")
                async with self.lock:
                    task.state = "failed"
                    task.error = TaskError(
                        code="INTERNAL",
                        message=f"Internal error during model analysis: {exc}",
                        retryable=False,
                    )
                    task.updated_at = datetime.now(timezone.utc)
                return

            # 3. State: analyzing -> awaiting_approval
            if settings.MOCK_MODE:
                await asyncio.sleep(1.0)

            async with self.lock:
                # If cancelled during analysis, do not overwrite state
                if task.state != "cancelled":
                    task.analysis = analysis
                    task.state = "awaiting_approval"
                    task.updated_at = datetime.now(timezone.utc)

        except asyncio.CancelledError:
            logger.info("Task pipeline cancelled: %s", task_id)
        except Exception as exc:
            logger.exception("Task pipeline fatal error: %s", task_id)
            async with self.lock:
                t = self.tasks.get(task_id)
                if t and t.state not in TERMINAL_STATES:
                    t.state = "failed"
                    t.error = TaskError(
                        code="INTERNAL",
                        message=str(exc),
                        retryable=False,
                    )
                    t.updated_at = datetime.now(timezone.utc)

    async def _execute_proposal(self, task_id: str, proposal: Proposal):
        """Executes patches and commands in the approved proposal."""
        if settings.MOCK_MODE:
            await asyncio.sleep(1.0)

        task = self.tasks.get(task_id)
        if not task or task.state == "cancelled":
            return

        action_results: list[ActionResult] = []
        overall_success = True

        # 1. Apply file patches
        for idx, patch in enumerate(proposal.files):
            action_id = f"act-{proposal.id}-patch-{idx}"
            token = generate_approval_token(
                action_id=action_id,
                secret=settings.APPROVAL_SECRET,
                patch=patch,
            )
            req = ActionRequest(
                action_id=action_id,
                kind="apply_patch",
                patch=patch,
                working_dir=settings.ALLOWED_ROOT,
                approval_token=token,
            )
            res = perception.sandbox.execute(req, secret=settings.APPROVAL_SECRET, allowed_root=settings.ALLOWED_ROOT)
            action_results.append(res)
            if res.status != "ok":
                overall_success = False
                break

        # 2. Run commands if patches succeeded
        if overall_success:
            for idx, cmd in enumerate(proposal.commands):
                action_id = f"act-{proposal.id}-cmd-{idx}"
                token = generate_approval_token(
                    action_id=action_id,
                    secret=settings.APPROVAL_SECRET,
                    command=cmd,
                )
                req = ActionRequest(
                    action_id=action_id,
                    kind="run_command",
                    command=cmd,
                    working_dir=settings.ALLOWED_ROOT,
                    approval_token=token,
                )
                res = perception.sandbox.execute(req, secret=settings.APPROVAL_SECRET, allowed_root=settings.ALLOWED_ROOT)
                action_results.append(res)
                if res.status != "ok":
                    overall_success = False
                    break

        async with self.lock:
            if task.state != "cancelled":
                task.action_results = action_results
                task.updated_at = datetime.now(timezone.utc)
                if overall_success:
                    task.state = "completed"
                else:
                    task.state = "failed"
                    task.error = TaskError(
                        code="EXECUTION_FAILED",
                        message="One or more proposal actions failed or were denied during execution",
                        retryable=False,
                    )


task_manager = TaskManager()
