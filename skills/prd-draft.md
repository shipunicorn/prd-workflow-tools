# prd-draft

Use this skill when a user gives a product idea, feature concept, bug, or GitHub issue idea and wants it turned into a local PRD draft.

## Goal

Create or update a Markdown PRD at:

```text
<repo>/_workspace/github-issues/<slug>.md
```

Open the draft in `prd-viewer` only when unresolved review questions remain.

## Workflow

1. Resolve the target repo and a concise lowercase slug.
2. Inspect the relevant code, docs, routes, UI, tests, or issue context before writing.
3. Draft a decision-oriented PRD with clear scope, requirements, acceptance criteria, test plan, and open questions.
4. If no open questions remain, the draft is ready to publish through your issue-publishing workflow.
5. If open questions remain, run:

```bash
python tools/prd-viewer/prd_viewer.py open --repo <repo-or-alias> <slug>
```

## Draft Shape

```markdown
---
title: "Short PRD title"
status: Draft
area: not-set
feature: Feature name
recommendation: Short recommended approach
open_questions: None
publish_readiness: Ready to publish
repo: "/path/to/repo"
remote: "origin URL or unknown"
slug: "short-slug"
---

# Short PRD title

## Summary
## Problem
## Goals
## Non-Goals
## Proposed Scope
## Requirements
## Options And Recommendation
## Acceptance Criteria
## Test Plan
## Open Questions
## Feedback Notes
```

Keep open questions parseable: numbered title, `Decision type`, `Issue`, `Why it matters`, and an options table with `Option`, `Pros`, `Cons`, and `Recommendation`.
