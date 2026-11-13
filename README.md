# agent-claim-verification

Agents sometimes report work they never did. They say "I saved the report to `out/report.md`" when no write call was made, or "according to `docs/policy.md`" without having opened the file. In a single chat a human notices. In a system where agents hand work to each other, nobody notices, and the false claim becomes the next agent's input.

I run a production multi-agent system of 61 Claude-based agents (engineering, editing, legal review, audit) that delegate to each other. To catch this failure I added a verification layer to the runtime. This repository contains:

- `claimcheck/`, a small, dependency-free reimplementation of that layer's core idea, with tests
- `data/monthly_counts.csv`, aggregate counts from the production audit log
- this write-up: what the layer does, what it found, and where it was wrong

The production system is closed source. The code here is an independent rewrite of the idea, not the production code. No message content from the production system is published here, only counts.

## How the check works

Every run produces two things: the agent's final message, and a log of the tools it actually called. The check compares them.

1. **Extract claims.** Find sentences where the agent says it wrote a file or relied on a source.
2. **Match against the log.** A write claim needs a matching write call. A citation needs a matching read.
3. **Nudge.** If a claim has no matching call, the agent gets a message that names the unsupported claim and asks it either to do the work with a real tool call or to correct the answer.
4. **Block.** If the agent still does not recover, the answer is not delivered.

In production the agent gets up to two corrective nudges before the block.

```python
from claimcheck import ToolCall, verify

report = verify(
    "I have saved the summary to reports/q3.md.",
    [ToolCall("read_file", "data/q3.csv")],
)
report.ok           # False
report.findings     # [Finding(kind='claimed_write_no_call', ...)]
```

`run_with_guard(step)` wraps an agent turn with the nudge and block loop. See `tests/test_core.py`.

## What it found

Window: 15 August to 11 November 2026. 61 agents, 3,169 runs, 30,973 audited events. Source: the system's audit table, counted on 14 November 2026.

| Event | Count | Meaning |
|---|---:|---|
| Claimed a write, no write call | 187 events in 133 runs | "I saved it" with nothing saved |
| Cited a source, no read call | 162 events in 112 runs, 23 agents | "According to X" without opening X |
| Citation still unsupported after nudges | 44 | the agent kept the citation |
| Fabricated tool transcript | 22 events, 6 agents | the agent wrote out a fake tool call and its "result" as prose instead of calling the tool |
| Blocked before delivery | 55 runs, 18 agents | unsupported claims that never recovered |

**Most agents recover when told.** Of the 133 runs with an unsupported write claim, 92 (69%) recovered: 68 after the first nudge and 24 after the second. The other 41 were blocked. A single, specific message ("you say you wrote X, there is no write call for X") is often enough. The same agents that fabricate will usually do the real work once the gap is pointed out.

**The rate fell over time.** Unsupported write claims per 100 runs: 8.9 in August, 7.2 in September, 3.8 in October, 2.9 in the first eleven days of November. Monthly counts are in `data/monthly_counts.csv`. I changed prompts and tooling during this period, so this is not a controlled measurement, only a trend.

## Auditing the auditor

A second agent reviews the whole system every day and reports problems to whoever owns the fix. In November it reported that the check itself was wrong in a specific way: it treated negated sentences as claims. "I did not write the file because the task was cancelled" was counted as a false write claim.

Checking the logged previews, 46 of the 187 unsupported write events contain a negation phrase. Not all of those are false alarms, but some are, so the counts above are an upper bound. The rewrite in this repository skips negated sentences (`test_negated_sentence_is_not_a_claim`). That is a simple fix that has its own failure mode: "I wrote the file, not the summary" would now be skipped too. A pattern-based checker trades one error for another, which is part of why I think this needs real research.

## Limits

- Pattern matching on text is cheap and brittle. It misses claims phrased in unexpected ways and produces false alarms on negations, quotations and plans ("I will write the file").
- A matching tool call shows that a write happened, not that the right content was written.
- The production agents work mostly in Turkish. The patterns here are English only.
- The counts come from one system with one operator. They show that the failure is common and that a nudge often fixes it. They do not show how general the numbers are.

## Run the tests

```
python -m pytest
```

Python 3.10 or newer, no other dependencies.

## About

Built by Ali Yıldırım. The production system, its audit data and the analysis are mine. I wrote this repository with Claude's help.

MIT licensed.
