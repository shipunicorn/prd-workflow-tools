# prd-viewer

Standalone local viewer for PRD Markdown drafts.

It reads PRDs from:

```text
<repo>/_workspace/github-issues/<slug>.md
```

The viewer runs independently from the target app.

## Commands

List drafts:

```powershell
python .\tools\prd-viewer\prd_viewer.py list --repo C:\path\to\repo
```

Open the draft list. This starts the server if needed:

```powershell
python .\tools\prd-viewer\prd_viewer.py open --repo C:\path\to\repo
```

Open a specific PRD:

```powershell
python .\tools\prd-viewer\prd_viewer.py open --repo C:\path\to\repo example-prd-slug
```

The `open` command uses the system default browser.

Equivalent PowerShell wrapper:

```powershell
.\tools\prd-viewer\prd-viewer.ps1 open --repo C:\path\to\repo example-prd-slug
```

Run the server in the foreground:

```powershell
python .\tools\prd-viewer\prd_viewer.py serve --host 127.0.0.1 --port 4768
```

## Runtime Files

Launcher logs and pid files are written outside repositories. Override with
`PRD_VIEWER_TMP` when needed.

```text
~/.prd-viewer/
```

## URLs

Default server:

```text
http://127.0.0.1:4768/?repo=<repo-or-alias>
http://127.0.0.1:4768/?repo=<repo-or-alias>&prd=<slug>
http://127.0.0.1:4768/api/prds?repo=<repo-or-alias>
http://127.0.0.1:4768/health
```

`--repo` accepts paths by default. It can also accept aliases from a JSON file
configured through `PRD_PROJECTS_FILE`:

```powershell
$env:PRD_PROJECTS_FILE = "C:\path\to\dev_projects.json"
```

The alias file shape is:

```json
{
  "projects": {
    "app": { "root": "C:\\path\\to\\repo" }
  }
}
```
