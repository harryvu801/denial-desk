"""Proposers: the one interface behind which a model is called, recorded, replayed or faked.

  AnthropicProposer  calls Claude with structured outputs. Needs credentials; costs money.
  RecordingProposer  wraps another proposer and appends every call to a JSONL recording.
  ReplayProposer     serves a recording. No key, no network, no cost — what the demo, CI
                     and anyone cloning the repo use.
  StubProposer       a function you pass in. For tests and plumbing checks.

Recordings are keyed by (line, model, prompt hash). Edit the prompt and the hash changes,
so replay reports `missing_recording` instead of serving answers to a prompt that no
longer exists.

`Protocol` is Python's structural interface: like a TypeScript interface, anything with the
right methods satisfies it without inheriting from it.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import ValidationError

from denial_desk.agent.input import ProposalRequest
from denial_desk.agent.schemas import ModelProposal, strict_json_schema

if TYPE_CHECKING:  # import only for type checking; the SDK is not needed to replay
    import anthropic
    from anthropic.types import MessageParam, OutputConfigParam

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class Failure(StrEnum):
    INVALID_OUTPUT = "invalid_output"  # failed validation twice
    REFUSAL = "refusal"
    TRUNCATED = "truncated"  # hit max_tokens
    MISSING_RECORDING = "missing_recording"
    PLACEHOLDER_PROMPT = "placeholder_prompt"


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ProposalOutcome:
    """Exactly one of `proposal` / `failure` is set. A failure always means: a human decides."""

    line_control_number: str
    model: str
    prompt_id: str
    proposal: ModelProposal | None
    failure: Failure | None
    raw: str
    usage: Usage
    latency_ms: float
    attempts: int = 1


class Proposer(Protocol):
    @property
    def model(self) -> str: ...

    def propose(self, request: ProposalRequest) -> ProposalOutcome: ...


def _failed(req: ProposalRequest, model: str, failure: Failure, raw: str = "") -> ProposalOutcome:
    return ProposalOutcome(
        req.line_control_number, model, req.prompt.id, None, failure, raw, Usage(), 0.0
    )


class AnthropicProposer:
    def __init__(
        self, client: anthropic.Anthropic, model: str, effort: Effort, max_tokens: int
    ) -> None:
        self._client = client
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens
        self._output_config: OutputConfigParam = {
            "effort": effort,
            "format": {"type": "json_schema", "schema": strict_json_schema(ModelProposal)},
        }

    @property
    def model(self) -> str:
        return self._model

    def propose(self, request: ProposalRequest) -> ProposalOutcome:
        if request.prompt.is_placeholder:
            return _failed(request, self._model, Failure.PLACEHOLDER_PROMPT)
        messages: list[MessageParam] = [{"role": "user", "content": request.user}]
        usage = Usage()
        started = time.perf_counter()
        raw = ""

        def outcome(
            proposal: ModelProposal | None, fail: Failure | None, n: int
        ) -> ProposalOutcome:
            elapsed = (time.perf_counter() - started) * 1000
            return ProposalOutcome(
                request.line_control_number,
                self._model,
                request.prompt.id,
                proposal,
                fail,
                raw,
                usage,
                elapsed,
                n,
            )

        for attempt in (1, 2):
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=request.system,
                messages=messages,
                output_config=self._output_config,
            )
            usage = Usage(
                usage.input_tokens + response.usage.input_tokens,
                usage.output_tokens + response.usage.output_tokens,
            )
            raw = next((b.text for b in response.content if b.type == "text"), "")
            if response.stop_reason == "refusal":
                return outcome(None, Failure.REFUSAL, attempt)
            if response.stop_reason == "max_tokens":
                return outcome(None, Failure.TRUNCATED, attempt)
            try:
                return outcome(ModelProposal.model_validate_json(raw), None, attempt)
            except ValidationError as exc:
                # One retry with the error fed back, then fail closed (ADR-010).
                messages += [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": f"That output failed validation: {exc}."
                        " Return corrected JSON only.",
                    },
                ]
        return outcome(None, Failure.INVALID_OUTPUT, 2)


def _key(line_control_number: str, model: str, prompt_id: str) -> str:
    return f"{line_control_number}|{model}|{prompt_id}"


class RecordingProposer:
    def __init__(self, inner: Proposer, path: Path) -> None:
        self._inner = inner
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def model(self) -> str:
        return self._inner.model

    def propose(self, request: ProposalRequest) -> ProposalOutcome:
        outcome = self._inner.propose(request)
        if outcome.failure is not Failure.PLACEHOLDER_PROMPT:
            row = {
                "key": _key(outcome.line_control_number, outcome.model, outcome.prompt_id),
                "raw": outcome.raw,
                "failure": outcome.failure.value if outcome.failure else None,
                "usage": asdict(outcome.usage),
                "latency_ms": round(outcome.latency_ms, 1),
                "attempts": outcome.attempts,
            }
            with self._path.open("a") as fh:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        return outcome


class ReplayProposer:
    def __init__(self, path: Path, model: str) -> None:
        self._model = model
        self._rows: dict[str, dict[str, Any]] = {}
        if path.exists():
            for line in path.read_text().splitlines():
                row = json.loads(line)
                self._rows[row["key"]] = row  # a later recording of the same key wins

    @property
    def model(self) -> str:
        return self._model

    def propose(self, request: ProposalRequest) -> ProposalOutcome:
        row = self._rows.get(_key(request.line_control_number, self._model, request.prompt.id))
        if row is None:
            return _failed(request, self._model, Failure.MISSING_RECORDING)
        failure = Failure(row["failure"]) if row["failure"] else None
        proposal = None if failure else ModelProposal.model_validate_json(row["raw"])
        return ProposalOutcome(
            request.line_control_number,
            self._model,
            request.prompt.id,
            proposal,
            failure,
            row["raw"],
            Usage(**row["usage"]),
            row["latency_ms"],
            row["attempts"],
        )


class StubProposer:
    def __init__(
        self, decide: Callable[[ProposalRequest], ModelProposal], model: str = "stub"
    ) -> None:
        self._decide = decide
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def propose(self, request: ProposalRequest) -> ProposalOutcome:
        proposal = self._decide(request)
        return ProposalOutcome(
            request.line_control_number,
            self._model,
            request.prompt.id,
            proposal,
            None,
            proposal.model_dump_json(),
            Usage(),
            0.0,
        )
