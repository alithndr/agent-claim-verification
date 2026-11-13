from claimcheck import ToolCall, extract_claims, run_with_guard, verify


def test_supported_write_claim_passes():
    text = "I have written the report to reports/q3-summary.md."
    report = verify(text, [ToolCall("write_file", "reports/q3-summary.md")])
    assert report.ok
    assert [c.kind for c in report.claims] == ["write"]


def test_unsupported_write_claim_is_flagged():
    report = verify("Saved to output/plan.md.", [])
    assert [f.kind for f in report.findings] == ["claimed_write_no_call"]
    assert report.findings[0].claim.target == "output/plan.md"


def test_read_call_does_not_support_a_write_claim():
    report = verify("I wrote notes.txt", [ToolCall("read_file", "notes.txt")])
    assert not report.ok


def test_negated_sentence_is_not_a_claim():
    # The production guard counted sentences like this one as claims.
    assert extract_claims("I did not write output/plan.md because the task was cancelled.") == []
    assert extract_claims("No file was saved to output/plan.md.") == []


def test_unsupported_citation_is_flagged():
    report = verify("According to docs/policy.md, refunds take 14 days.", [])
    assert [f.kind for f in report.findings] == ["claimed_citation_no_read"]


def test_supported_citation_passes_with_relative_paths():
    report = verify(
        "According to docs/policy.md, refunds take 14 days.",
        [ToolCall("read_file", "./project/docs/policy.md")],
    )
    assert report.ok


def test_guard_recovers_after_one_nudge():
    calls = []

    def step(feedback):
        if feedback is None:
            return "I have saved the draft to out/draft.md.", list(calls)
        calls.append(ToolCall("write_file", "out/draft.md"))
        return "I have saved the draft to out/draft.md.", list(calls)

    result = run_with_guard(step)
    assert not result.first_report.ok
    assert result.delivered
    assert result.attempts == 2


def test_guard_blocks_when_agent_repeats_the_claim():
    def step(feedback):
        return "I have saved the draft to out/draft.md.", []

    result = run_with_guard(step)
    assert not result.delivered
    assert result.attempts == 2
