# PRD Workflow Tools

Small, shareable PRD workflow kit for AI-assisted product planning.

## Repository Layout

```text
skills/
  prd-draft.md
  prd-feedback.md
  prd-implement.md
tools/
  prd-viewer/
```

The skill files are plain Markdown so they can be pasted into Claude, Codex, or another agent's custom-instruction system.

## Viewer Usage

The viewer is a small local Python tool for opening PRD Markdown drafts from a repo's `_workspace\github-issues` folder.

```powershell
python .\tools\prd-viewer\prd_viewer.py open --repo C:\path\to\repo your-prd-slug
```

macOS/Linux:

```bash
python3 ./tools/prd-viewer/prd_viewer.py open --repo /path/to/repo your-prd-slug
```

The launcher starts a local server on `http://127.0.0.1:4768` when needed.

## Adapting Paths

Windows:

- Use PowerShell examples and backslash paths such as `C:\path\to\repo`.
- Optional repo aliases can be configured with `$env:PRD_PROJECTS_FILE = "C:\path\to\dev_projects.json"`.
- Optional temp location: `$env:PRD_VIEWER_TMP = "C:\path\to\tmp\prd-viewer"`.

iOS and macOS:

- On macOS, use `python3`, forward-slash paths, and shell exports such as `export PRD_PROJECTS_FILE=/path/to/dev_projects.json`.
- On iOS, use the Markdown skills as reference prompts. Running the Python viewer usually requires a Python-capable app or a remote dev machine because normal iOS apps do not expose a full local repo workflow.

## Claude vs Codex

Claude:

- Paste a skill file into a project instruction, custom command, or prompt.
- Replace tool-specific lines with the commands Claude can run in your environment.
- If Claude cannot open local browser windows, ask it to print the viewer URL after starting the server.

Codex:

- Put the Markdown skills wherever your Codex setup loads skills or agent instructions.
- Keep the instruction to inspect the repo before editing, preserve unrelated worktree changes, and run focused verification.
- For local app/browser limitations, adapt the browser-opening rules to your Codex client.

## Privacy Notes

This repository avoids personal usernames, private repo names, and machine-specific absolute paths. Configure local paths through command arguments or environment variables.
