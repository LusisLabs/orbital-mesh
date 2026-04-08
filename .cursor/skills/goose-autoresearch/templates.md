# Templates

## Lead Brief

Use this template in the session `manifest.json` and `prompts/lead.md`:

```markdown
# Lead Brief

## Research Question
[exact question]

## Why This Matters
[operator or product context]

## Scope
- Include:
- Exclude:

## Success Rubric
- Correctness:
- Evidence quality:
- Actionability:
- Novelty:

## Session Constraints
- Time budget:
- Tool budget:
- Preferred sources:
- Must-avoid failure modes:
```

## Worker Prompt

```markdown
You are `worker-[id]` in a clustered Goose autoresearch session.

Role: [baseline | skeptic | deep-dive | editor]
Goal: [specific sub-question]

Session question:
[full question]

Required behavior:
- Stay focused on this worker role.
- Prefer concrete evidence over broad claims.
- Surface uncertainty explicitly.
- End with a compact verdict and next checks.

Return using this structure:
## Summary
## Key Evidence
## Risks / Uncertainty
## Recommendation
## Follow-up Questions
```

## Scorecard

Write `results/scorecard.md` using:

```markdown
# Scorecard

| Worker | Correctness | Evidence | Novelty | Actionability | Repo Reality | Notes |
|---|---:|---:|---:|---:|---:|---|
| worker-01 |  |  |  |  |  |  |
| worker-02 |  |  |  |  |  |  |
| worker-03 |  |  |  |  |  |  |
| worker-04 |  |  |  |  |  |  |

## Convergence
- Consensus:
- Disagreements:
- Missing evidence:
- Decision on next wave:
```

## Final Synthesis Prompt

```markdown
You are the lead synthesizer for a clustered Goose autoresearch session.

Your job:
- compare worker outputs
- resolve direct contradictions when evidence is sufficient
- preserve disagreement when evidence is insufficient
- recommend the clearest next action

Inputs:
- session manifest
- worker outputs
- scorecard
- operator notes

Return using this structure:
# Final Report

## Executive Summary
## Strongest Findings
## Conflicts And Unknowns
## Recommended Next Action
## Appendix: Winning Evidence
```
