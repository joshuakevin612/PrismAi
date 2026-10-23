"""backend/model_client.py - Nebius / Nemotron client with schema validation, retry loop, and mock fallback."""

import json
import logging
from typing import Any, Optional
from pydantic import BaseModel, Field, ValidationError

from shared.schemas import Analysis, PatchFile, Proposal
from perception.sandbox import ActionRequest, validate_action
from backend.config import settings

logger = logging.getLogger("backend.model_client")


class ProposalFromModel(BaseModel):
    id: str
    title: str
    rationale: str
    risk: str = "medium"  # "low", "medium", "high"
    files: list[PatchFile] = Field(default_factory=list)
    commands: list[list[str]] = Field(default_factory=list)


class AnalysisFromModel(BaseModel):
    summary: str
    root_cause: str
    explanation: str
    confidence: float = Field(ge=0.0, le=1.0)
    proposals: list[ProposalFromModel] = Field(default_factory=list)


class ModelClientException(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


SYSTEM_PROMPT = """You are an automated coding analysis and remediation engine.
Analyze the provided developer context (terminal errors, pull request diffs, OCR screen text, and command).
You MUST respond ONLY with a JSON object matching this schema:
{
  "summary": "Short one-sentence summary of the remediation",
  "root_cause": "Clear statement of what went wrong",
  "explanation": "Detailed markdown explanation of the bug and the proposed solution",
  "confidence": 0.95,
  "proposals": [
    {
      "id": "prop-1",
      "title": "Title of the proposal",
      "rationale": "Why this fixes the root cause",
      "risk": "low",
      "files": [
        {
          "path": "relative/path/to/file.py",
          "unified_diff": "--- a/file.py\\n+++ b/file.py\\n@@ -1,1 +1,1 @@\\n-old\\n+new\\n"
        }
      ],
      "commands": [
        ["pytest", "tests/"]
      ]
    }
  ]
}

CRITICAL RULES:
1. Return valid JSON only. No markdown formatting ticks around the JSON, no surrounding commentary.
2. Every command in 'commands' must be an argv list of strings (e.g. ["pytest", "tests/test_x.py"]), NEVER a shell string or piped command.
3. Keep file diffs minimal, precise, and targeted to the root cause.
"""


def enrich_analysis_with_policy_check(
    raw_analysis: AnalysisFromModel,
    allowed_root: str,
) -> Analysis:
    """Runs M1 validate_action on every proposed patch and command in the model output.
    
    Sets policy_ok and policy_denial_reason accordingly.
    """
    validated_proposals: list[Proposal] = []

    for prop in raw_analysis.proposals:
        risk_val = prop.risk if prop.risk in ["low", "medium", "high"] else "medium"
        proposal_policy_ok = True
        proposal_denial_reason: Optional[str] = None

        # 1. Validate files/patches
        for f in prop.files:
            dry_req = ActionRequest(
                action_id=f"validate-{prop.id}-patch",
                kind="apply_patch",
                patch=f,
                working_dir=allowed_root,
                approval_token="dry-run",
            )
            ok, reason = validate_action(dry_req, allowed_root=allowed_root)
            if not ok:
                proposal_policy_ok = False
                proposal_denial_reason = reason
                break

        # 2. Validate commands
        if proposal_policy_ok:
            for cmd in prop.commands:
                dry_req = ActionRequest(
                    action_id=f"validate-{prop.id}-cmd",
                    kind="run_command",
                    command=cmd,
                    working_dir=allowed_root,
                    approval_token="dry-run",
                )
                ok, reason = validate_action(dry_req, allowed_root=allowed_root)
                if not ok:
                    proposal_policy_ok = False
                    proposal_denial_reason = reason
                    break

        validated_proposals.append(
            Proposal(
                id=prop.id,
                title=prop.title,
                rationale=prop.rationale,
                risk=risk_val,  # type: ignore[arg-type]
                files=prop.files,
                commands=prop.commands,
                policy_ok=proposal_policy_ok,
                policy_denial_reason=proposal_denial_reason,
            )
        )

    return Analysis(
        summary=raw_analysis.summary,
        root_cause=raw_analysis.root_cause,
        explanation=raw_analysis.explanation,
        confidence=raw_analysis.confidence,
        proposals=validated_proposals,
    )


class ModelClient:
    """Client for Nebius Nemotron model with retry loop and validation."""

    def __init__(self, api_key: str = "", base_url: str = "", model: str = ""):
        self.api_key = api_key or settings.NEBIUS_API_KEY
        self.base_url = base_url or settings.NEBIUS_BASE_URL
        self.model = model or settings.NEMOTRON_MODEL

    async def analyze(
        self,
        command: str,
        budgeted_context: dict,
        allowed_root: str = ".",
    ) -> Analysis:
        """Analyzes budgeted context and returns a validated Analysis."""
        if settings.MOCK_MODE:
            return self._mock_analyze(command, budgeted_context, allowed_root)

        return await self._live_analyze(command, budgeted_context, allowed_root)

    def _mock_analyze(
        self,
        command: str,
        budgeted_context: dict,
        allowed_root: str = ".",
    ) -> Analysis:
        """Returns canned analysis or simulates drill failures based on command."""
        cmd_lower = command.lower()

        # Drill: Model unavailable (retryable)
        if "trigger-model-unavailable" in cmd_lower or "model_unavailable" in cmd_lower:
            raise ModelClientException(
                code="MODEL_UNAVAILABLE",
                message="Nebius endpoint unreachable: connection timeout after 10000ms",
                retryable=True,
            )

        # Drill: Model invalid response (non-retryable)
        if "trigger-model-invalid" in cmd_lower or "model_invalid_response" in cmd_lower:
            raise ModelClientException(
                code="MODEL_INVALID_RESPONSE",
                message="Output failed Pydantic validation after 2 retries: missing field 'summary'",
                retryable=False,
            )

        # Drill: Policy denied proposal
        if "trigger-policy-denied" in cmd_lower or "policy_denied" in cmd_lower:
            raw = AnalysisFromModel(
                summary="Execute aggressive system cleanup",
                root_cause="Build cache corruption",
                explanation="### Cleanup\nRemoves unallowlisted directories using forbidden command `rm`.",
                confidence=0.85,
                proposals=[
                    ProposalFromModel(
                        id="prop-denied-1",
                        title="Purge root files recursively",
                        rationale="Cleans out stuck files",
                        risk="high",
                        files=[],
                        commands=[["rm", "-rf", "/tmp/cache"]],
                    )
                ],
            )
            return enrich_analysis_with_policy_check(raw, allowed_root=allowed_root)

        # Default happy-path mock analysis
        raw = AnalysisFromModel(
            summary="Fix KeyError when accessing price in items payload",
            root_cause="KeyError: 'price' triggered in app/main.py because items payload lacks default fallback.",
            explanation="### Root Cause\nThe pricing loop accessed `item['price']` directly without ensuring the key exists or providing a default value of 0.\n\n### Recommended Remediation\nUpdate line 15 to use `item.get('price', 0)` and run tests to verify.",
            confidence=0.96,
            proposals=[
                ProposalFromModel(
                    id="prop-mock-1",
                    title="Safely retrieve price with .get('price', 0)",
                    rationale="Eliminates KeyError when price key is omitted in dictionary",
                    risk="low",
                    files=[
                        PatchFile(
                            path="app/main.py",
                            unified_diff="--- a/app/main.py\n+++ b/app/main.py\n@@ -14,2 +14,2 @@\n-    return sum(item['price'] for item in items)\n+    return sum(item.get('price', 0) for item in items)\n",
                        )
                    ],
                    commands=[["python", "-c", "print('Remediation verified')"]],
                )
            ],
        )
        return enrich_analysis_with_policy_check(raw, allowed_root=allowed_root)

    async def _live_analyze(
        self,
        command: str,
        budgeted_context: dict,
        allowed_root: str = ".",
    ) -> Analysis:
        """Calls Nebius Studio OpenAI-compatible API with retry loop."""
        import httpx

        # Quoted prompt structure to reduce prompt injection risk
        user_message_content = (
            f"Please analyze the following bug context and command.\n\n"
            f"=== TARGET COMMAND ===\n"
            f"```\n{command}\n```\n\n"
            f"=== CONTEXT DATA (UNTRUSTED QUOTED BLOCKS) ===\n"
            f"```json\n{json.dumps(budgeted_context, indent=2)}\n```\n\n"
            f"Produce the JSON remediation plan matching the schema."
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message_content},
        ]

        retries_remaining = 2
        last_error_msg = ""

        client = httpx.AsyncClient(
            base_url=self.base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

        try:
            while retries_remaining >= 0:
                try:
                    response = await client.post(
                        "/chat/completions",
                        json={
                            "model": self.model,
                            "messages": messages,
                            "temperature": 0.1,
                            "response_format": {"type": "json_object"},
                        },
                    )

                    if response.status_code >= 500 or response.status_code == 429:
                        raise ModelClientException(
                            code="MODEL_UNAVAILABLE",
                            message=f"Nebius endpoint returned status {response.status_code}: {response.text}",
                            retryable=True,
                        )

                    if response.status_code != 200:
                        raise ModelClientException(
                            code="MODEL_UNAVAILABLE",
                            message=f"Nebius request failed ({response.status_code}): {response.text}",
                            retryable=True,
                        )

                    data = response.json()
                    raw_text = data["choices"][0]["message"]["content"]

                    # Strip potential markdown fences if model included them
                    cleaned_text = raw_text.strip()
                    if cleaned_text.startswith("```json"):
                        cleaned_text = cleaned_text[7:]
                    if cleaned_text.startswith("```"):
                        cleaned_text = cleaned_text[3:]
                    if cleaned_text.endswith("```"):
                        cleaned_text = cleaned_text[:-3]
                    cleaned_text = cleaned_text.strip()

                    parsed_json = json.loads(cleaned_text)
                    raw_analysis = AnalysisFromModel.model_validate(parsed_json)
                    return enrich_analysis_with_policy_check(raw_analysis, allowed_root=allowed_root)

                except (json.JSONDecodeError, ValidationError) as ve:
                    last_error_msg = str(ve)
                    retries_remaining -= 1
                    if retries_remaining < 0:
                        break

                    # Append retry instruction to dialogue
                    messages.append({"role": "assistant", "content": raw_text if 'raw_text' in locals() else ""})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"Your previous response failed Pydantic schema validation with error:\n"
                            f"{last_error_msg}\n"
                            f"Please correct your response and output strictly valid JSON conforming to the schema."
                        )
                    })

                except httpx.RequestError as exc:
                    raise ModelClientException(
                        code="MODEL_UNAVAILABLE",
                        message=f"Network error communicating with Nebius: {exc}",
                        retryable=True,
                    ) from exc

            # Exceeded retries
            raise ModelClientException(
                code="MODEL_INVALID_RESPONSE",
                message=f"Output failed Pydantic validation after 2 retries: {last_error_msg}",
                retryable=False,
            )

        finally:
            await client.aclose()
