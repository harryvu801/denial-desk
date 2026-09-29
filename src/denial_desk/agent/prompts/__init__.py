"""Versioned prompts.

Prompts live in files, are versioned by directory (v1/, v2/, ...), and every Resolution
records which version produced it. A prompt change is a code change and goes through the
eval gate like any other. See ADR-017.

TODO(stage-3): create v1/ with system.md, root_cause.md, appeal.md.
"""

CURRENT_VERSION = "v1"
