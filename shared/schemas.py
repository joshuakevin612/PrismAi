"""shared/schemas.py - Single source of truth for M1, M2, and M3 contracts.

Shared by perception, orchestration, and frontend. Regenerate OpenAPI and frontend types together.
Every top-level contract has schema_version: "1.0".
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Section 1: Member 1 <-> Member 2 Schemas (Context & Perception)
# ---------------------------------------------------------------------------

class GithubTarget(BaseModel):
    repo: str  # "owner/name"
    pr_number: int


class ContextRequest(BaseModel):
    auto: bool = True
    include_screen: bool = True
    include_terminal: bool = True
    include_processes: bool = False
    github: Optional[GithubTarget] = None


class ScreenContext(BaseModel):
    captured_at: datetime
    monitor: int
    width: int
    height: int
    ocr_text: str  # already secret-redacted
    ocr_confidence: Optional[float] = None  # 0..1
    screenshot_path: Optional[str] = None  # local file, served by backend


class TerminalError(BaseModel):
    exception_type: Optional[str] = None
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    raw_excerpt: str  # max 4000 chars, redacted


class ProcessInfo(BaseModel):
    pid: int
    name: str
    cmdline: str  # redacted
    cpu_percent: float
    mem_mb: float


class DiffFile(BaseModel):
    path: str
    status: Literal["added", "modified", "removed", "renamed"]
    additions: int
    deletions: int
    patch: Optional[str] = None  # unified diff, truncated if huge
    truncated: bool = False


class PullRequestContext(BaseModel):
    repo: str
    number: int
    title: str
    body: str
    base: str
    head: str
    files: list[DiffFile]


class ContextBundle(BaseModel):
    schema_version: str = "1.0"
    collected_at: datetime
    screen: Optional[ScreenContext] = None
    terminal_errors: list[TerminalError] = Field(default_factory=list)
    processes: list[ProcessInfo] = Field(default_factory=list)
    pull_request: Optional[PullRequestContext] = None
    warnings: list[str] = Field(default_factory=list)  # e.g. "TESSERACT_NOT_FOUND", "GITHUB_RATE_LIMITED"


# ---------------------------------------------------------------------------
# Sandbox & Action Schemas (M1 <-> M2 Execution Boundary)
# ---------------------------------------------------------------------------

class PatchFile(BaseModel):
    path: str
    unified_diff: str


Capability = Literal['screen', 'terminal', 'processes', 'modify_files', 'install_dependencies', 'network']


class AccessSettings(BaseModel):
    screen: bool = True
    terminal: bool = True
    processes: bool = True
    modify_files: bool = False
    install_dependencies: bool = False
    network: bool = False


class AccessUpdate(BaseModel):
    capability: Capability
    allowed: bool


class ExecutionAccess(BaseModel):
    modify_files: bool = False
    install_dependencies: bool = False
    network: bool = False


class PermissionRequest(BaseModel):
    id: str
    capabilities: list[Capability]
    reason: str
    phase: Literal['context', 'execution']
    status: Literal['pending', 'allowed', 'denied', 'cancelled'] = 'pending'
    proposal_id: Optional[str] = None
    commands: list[list[str]] = Field(default_factory=list)


class PermissionDecision(BaseModel):
    decision: Literal['allow', 'deny']


class ActionRequest(BaseModel):
    action_id: str
    kind: Literal["apply_patch", "run_command"]
    patch: Optional[PatchFile] = None  # for apply_patch
    command: Optional[list[str]] = None  # argv list, never a shell string
    working_dir: str
    approval_token: str  # issued by M2 on user approval
    access: ExecutionAccess = Field(default_factory=ExecutionAccess)


class ActionResult(BaseModel):
    action_id: str
    status: Literal["ok", "denied", "failed", "timeout"]
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    denial_reason: Optional[str] = None  # e.g. "COMMAND_NOT_ALLOWLISTED"
    duration_ms: int


# ---------------------------------------------------------------------------
# Section 2: Member 2 <-> Member 3 Schemas (REST API Boundary)
# ---------------------------------------------------------------------------

class CreateTaskRequest(BaseModel):
    command: str = Field(min_length=1, max_length=2000)
    context: ContextRequest = Field(default_factory=ContextRequest)


class Proposal(BaseModel):
    id: str
    title: str
    rationale: str
    risk: Literal["low", "medium", "high"]
    files: list[PatchFile] = Field(default_factory=list)
    commands: list[list[str]] = Field(default_factory=list)
    policy_ok: bool  # result of M1 validate_action
    policy_denial_reason: Optional[str] = None
    required_permissions: list[Capability] = Field(default_factory=list)
    requires_network: bool = False


class Analysis(BaseModel):
    summary: str
    root_cause: str
    explanation: str  # markdown
    confidence: float = Field(ge=0, le=1)
    proposals: list[Proposal] = Field(default_factory=list)
    needed_context: list[Literal['screen', 'terminal', 'processes']] = Field(default_factory=list)
    context_reason: str = ''


class TaskError(BaseModel):
    code: str
    message: str
    retryable: bool


class ContextSummary(BaseModel):  # lightweight, no huge blobs
    has_screenshot: bool
    ocr_excerpt: str  # first 1000 chars
    terminal_errors: list[TerminalError] = Field(default_factory=list)
    pr_title: Optional[str] = None
    pr_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


TaskState = Literal[
    "queued",
    "planning_context",
    "awaiting_permission",
    "collecting_context",
    "analyzing",
    "awaiting_approval",
    "executing",
    "completed",
    "rejected",
    "failed",
    "cancelled",
]


class TaskView(BaseModel):
    schema_version: str = "1.0"
    task_id: str
    state: TaskState
    command: str
    created_at: datetime
    updated_at: datetime
    context: Optional[ContextSummary] = None
    analysis: Optional[Analysis] = None
    action_results: list[ActionResult] = Field(default_factory=list)
    error: Optional[TaskError] = None
    selected_sources: list[Capability] = Field(default_factory=list)
    permission_requests: list[PermissionRequest] = Field(default_factory=list)
    task_grants: list[Capability] = Field(default_factory=list)
    access: AccessSettings = Field(default_factory=AccessSettings)


class DecisionRequest(BaseModel):
    proposal_id: str
    decision: Literal["approve", "reject"]
    reason: Optional[str] = None


class TaskCreatedResponse(BaseModel):
    schema_version: str = "1.0"
    task_id: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    retryable: bool


class ErrorResponse(BaseModel):
    error: ErrorDetail


class HealthResponse(BaseModel):
    schema_version: str = "1.0"
    backend: bool = True
    m1: dict[str, bool] = Field(default_factory=dict)
