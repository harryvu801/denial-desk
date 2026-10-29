"""Versioned prompts.

Prompts live in files under <task>/<version>/, never in Python strings. Each loaded prompt
carries a short hash of its exact text, which is recorded with every model call: replayed
responses are keyed by it, so editing a prompt can never silently reuse old answers.
See ADR-017.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).parent
PLACEHOLDER_MARKER = "TODO(author): write this prompt"


@dataclass(frozen=True)
class Prompt:
    task: str
    version: str
    system: str
    user_template: Template
    sha: str  # first 12 hex chars of sha256(system + user template)

    @property
    def is_placeholder(self) -> bool:
        return PLACEHOLDER_MARKER in self.system

    @property
    def id(self) -> str:
        return f"{self.task}/{self.version}@{self.sha}"


def load_prompt(task: str, version: str) -> Prompt:
    directory = PROMPTS_DIR / task / version
    system = (directory / "system.md").read_text()
    user = (directory / "user.md").read_text()
    sha = hashlib.sha256((system + "\0" + user).encode()).hexdigest()[:12]
    return Prompt(task, version, system, Template(user), sha)
