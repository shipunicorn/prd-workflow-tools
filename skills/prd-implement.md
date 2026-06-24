# prd-implement

Use this skill when a published PRD or GitHub issue is ready to implement.

## Goal

Move from issue or PRD requirements to a focused code change, tests, and verification.

## Workflow

1. Resolve the issue, PRD, repo, branch, and local worktree state.
2. Read the issue body, requirements, acceptance criteria, and test plan.
3. Inspect the relevant code paths before editing.
4. Decide the verification approach:
   - small change: write or update focused tests after implementation
   - medium or large change: add focused tests first, capture the baseline, then implement and rerun
5. Implement the smallest change that satisfies the PRD.
6. Follow local conventions for routes, templates, data access, migrations, styling, tests, and docs.
7. Run focused functional and UI verification.
8. Report changed files, commands run, results, and any blocked manual follow-up.

## Stop Conditions

Pause before destructive work such as dropping data, resetting branches, deleting user changes, running destructive migrations, pushing or merging without permission, or making a risky choice when requirements are materially ambiguous.
