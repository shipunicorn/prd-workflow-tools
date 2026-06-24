# prd-feedback

Use this skill when a user gives feedback on an unpublished local PRD draft and wants the Markdown source updated.

## Goal

Incorporate feedback into:

```text
<repo>/_workspace/github-issues/<slug>.md
```

Then refresh `prd-viewer` if review questions or hold conditions remain.

## Workflow

1. Resolve the repo and slug from the user request, current repo, or draft filename.
2. Read the current Markdown before editing.
3. Classify the feedback:
   - requirement or behavior change
   - scope boundary or non-goal
   - answer to an open question
   - correction to framing or assumptions
   - wording or structure improvement
4. Make the smallest coherent edit that incorporates the feedback across requirements, recommendation, acceptance criteria, test plan, and open questions.
5. Remove resolved open questions and fold the decision into the body of the PRD.
6. Add or refine open questions only when a user-facing requirement, scope choice, acceptance criterion, or design decision remains unresolved.
7. If unresolved questions remain, run:

```bash
python tools/prd-viewer/prd_viewer.py open --repo <repo-or-alias> <slug>
```

If no questions or hold conditions remain, the draft is ready for your publish workflow.
