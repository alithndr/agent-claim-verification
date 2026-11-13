"""Compare what an agent says it did with the tool calls it actually made.

This is a small, dependency-free reimplementation of the idea behind the
verification layer in my production agent system. It is not the production
code. It keeps the two parts that matter:

1. extract claims from an agent's final message, and
2. check each claim against the run's tool-call log.

It also handles negation ("I did not write the file"), which the production
version got wrong. See README.md, "Auditing the auditor".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable

WRITE_TOOLS = frozenset({"write_file", "edit_file", "append_file", "create_file"})
READ_TOOLS = frozenset({"read_file", "web_fetch", "search", "open_url"})

# A file-like target: something with a slash or a dot extension.
_PATH = r"(?P<target>[\w./~-]+(?:/[\w.-]+|\.[A-Za-z0-9]{1,6}))"

_WRITE_PATTERNS = [
    re.compile(
        r"\b(?:I(?:'ve| have)?|have)\s+(?:wrote|written|saved|created|updated|edited)\b[^.\n]*?" + _PATH,
        re.I,
    ),
    re.compile(r"\b(?:saved|written|wrote)\s+(?:it\s+)?(?:to|in|into)\s+" + _PATH, re.I),
    re.compile(r"\b" + _PATH + r"\s+(?:has been|was|is now)\s+(?:written|saved|created|updated)", re.I),
]

_CITE_PATTERNS = [
    re.compile(r"\baccording to\s+" + _PATH, re.I),
    re.compile(r"\b(?:as stated|as described|as shown)\s+in\s+" + _PATH, re.I),
    re.compile(r"\bI\s+(?:read|reviewed|checked|opened)\s+" + _PATH, re.I),
]

_NEGATION = re.compile(
    r"\b(?:not|never|didn't|did not|haven't|have not|wasn't|was not|couldn't|could not|unable to|no file)\b",
    re.I,
)


@dataclass(frozen=True)
class ToolCall:
    name: str
    target: str = ""


@dataclass(frozen=True)
class Claim:
    kind: str  # "write" or "citation"
    target: str
    sentence: str


@dataclass
class Finding:
    kind: str  # "claimed_write_no_call" or "claimed_citation_no_read"
    claim: Claim


@dataclass
class Report:
    claims: list[Claim] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings


def _sentences(text: str) -> Iterable[str]:
    for part in re.split(r"(?<=[.!?])\s+|\n+", text):
        part = part.strip()
        if part:
            yield part


def _norm(path: str) -> str:
    return path.strip().strip("`'\"").rstrip(".,;:").lstrip("./")


def extract_claims(text: str) -> list[Claim]:
    """Find write and citation claims, skipping negated sentences."""
    claims: list[Claim] = []
    for sentence in _sentences(text):
        if _NEGATION.search(sentence):
            continue
        for kind, patterns in (("write", _WRITE_PATTERNS), ("citation", _CITE_PATTERNS)):
            for pattern in patterns:
                for match in pattern.finditer(sentence):
                    claim = Claim(kind, _norm(match.group("target")), sentence)
                    if claim not in claims:
                        claims.append(claim)
    return claims


def _matches(target: str, calls: Iterable[ToolCall], tools: frozenset[str]) -> bool:
    for call in calls:
        if call.name not in tools:
            continue
        done = _norm(call.target)
        if done == target or done.endswith("/" + target) or target.endswith("/" + done):
            return True
    return False


def verify(text: str, calls: Iterable[ToolCall]) -> Report:
    """Check every claim in ``text`` against the tool-call log ``calls``."""
    calls = list(calls)
    report = Report(claims=extract_claims(text))
    for claim in report.claims:
        if claim.kind == "write" and not _matches(claim.target, calls, WRITE_TOOLS):
            report.findings.append(Finding("claimed_write_no_call", claim))
        elif claim.kind == "citation" and not _matches(claim.target, calls, READ_TOOLS):
            report.findings.append(Finding("claimed_citation_no_read", claim))
    return report


def nudge(report: Report) -> str:
    """The corrective message sent back to the agent, once."""
    lines = ["Your answer makes claims that your tool calls do not support:"]
    for f in report.findings:
        verb = "write" if f.kind == "claimed_write_no_call" else "read"
        lines.append(f"- You say you used {f.claim.target!r}, but there is no {verb} call for it.")
    lines.append("Do the work with a tool call, or correct the answer. Do not repeat the claim.")
    return "\n".join(lines)


@dataclass
class GuardResult:
    text: str
    delivered: bool
    attempts: int
    first_report: Report
    final_report: Report


AgentStep = Callable[[str | None], tuple[str, list[ToolCall]]]


def run_with_guard(step: AgentStep, max_retries: int = 1) -> GuardResult:
    """Run one agent turn, nudge it if its claims are unsupported, block if it does not recover.

    ``step(feedback)`` runs the agent. ``feedback`` is None on the first call and
    the nudge text on a retry. It returns the final text and the tool calls of
    the whole run so far.
    """
    text, calls = step(None)
    first = report = verify(text, calls)
    attempts = 1
    while not report.ok and attempts <= max_retries:
        text, calls = step(nudge(report))
        report = verify(text, calls)
        attempts += 1
    return GuardResult(text, report.ok, attempts, first, report)
