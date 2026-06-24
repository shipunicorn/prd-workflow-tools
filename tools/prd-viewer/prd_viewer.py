r"""Standalone local viewer for repo PRD Markdown drafts.

The viewer is intentionally independent of any target app. It reads Markdown
drafts from <repo>/_workspace/github-issues and renders them with a bundled or
configured Markdown-to-HTML converter when available.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any


APP_ROOT = Path(__file__).resolve().parent
DEV_ROOT = Path(os.environ.get("DEV_ROOT", str(Path.home()))).expanduser().resolve()
DEFAULT_REPO = os.environ.get("PRD_DEFAULT_REPO", ".")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4768
DEFAULT_CONVERTER = APP_ROOT.parent / "md-to-html" / "md_to_html.py"
DEFAULT_PROJECTS_FILE = os.environ.get("PRD_PROJECTS_FILE")
DRAFTS_RELATIVE = Path("_workspace") / "github-issues"
TMP_ROOT = Path(os.environ.get("PRD_VIEWER_TMP", str(Path.home() / ".prd-viewer")))
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class PrdViewerError(RuntimeError):
    """Expected command failure with a user-facing message."""


@dataclass(frozen=True)
class Draft:
    slug: str
    markdown_path: Path
    html_path: Path
    title: str
    modified_at: float
    size: int
    signature: str


def validate_slug(value: str) -> str:
    slug = value.strip().lower()
    if not SLUG_RE.fullmatch(slug) or ".." in slug:
        raise PrdViewerError("Slug must contain only lowercase letters, numbers, dots, underscores, and hyphens.")
    return slug


def default_project_vars() -> dict[str, str]:
    home = Path.home()
    proj_root = Path(os.environ.get("PROJ_ROOT", str(DEV_ROOT))).expanduser()
    return {
        "DEV_ROOT": str(DEV_ROOT),
        "PROJ_ROOT": str(proj_root),
        "HOME": str(home),
        "USERPROFILE": str(home),
    }


def expand_project_root(value: str) -> Path:
    expanded = value
    variables = default_project_vars()
    variables.update({key: os.environ[key] for key in variables if key in os.environ})
    for key, replacement in variables.items():
        expanded = expanded.replace(f"${key}", replacement)
        expanded = expanded.replace(f"%{key}%", replacement)
    cygwin_drive = re.match(r"^/([a-zA-Z])/(.*)$", expanded)
    if cygwin_drive:
        expanded = f"{cygwin_drive.group(1).upper()}:/{cygwin_drive.group(2)}"
    return Path(expanded).expanduser()


def load_project_aliases(projects_file: str | Path | None = DEFAULT_PROJECTS_FILE) -> dict[str, dict[str, Any]]:
    if not projects_file:
        return {}
    projects_path = Path(projects_file).expanduser()
    if not projects_path.exists():
        return {}
    try:
        data = json.loads(projects_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PrdViewerError(f"Invalid project alias file {projects_path}: {exc}") from exc
    projects = data.get("projects", {})
    if not isinstance(projects, dict):
        raise PrdViewerError(f"Project alias file must contain a 'projects' object: {projects_path}")
    return projects


def resolve_project_alias(
    alias: str,
    projects: dict[str, dict[str, Any]],
    seen: set[str] | None = None,
) -> Path | None:
    if seen is None:
        seen = set()
    if alias in seen:
        raise PrdViewerError(f"Project alias cycle detected: {' -> '.join([*seen, alias])}")
    entry = projects.get(alias)
    if not isinstance(entry, dict):
        return None
    alias_for = entry.get("alias_for")
    if isinstance(alias_for, str):
        seen.add(alias)
        return resolve_project_alias(alias_for, projects, seen)
    root = entry.get("root") or entry.get("path")
    if not isinstance(root, str) or not root.strip():
        raise PrdViewerError(f"Project alias '{alias}' does not define a root path.")
    return expand_project_root(root).resolve()


def ensure_under_dev(path: Path) -> Path:
    resolved = path.resolve()
    dev = DEV_ROOT.resolve()
    try:
        resolved.relative_to(dev)
    except ValueError as exc:
        raise PrdViewerError(f"Repo must live under {dev}: {resolved}") from exc
    return resolved


def resolve_repo(value: str) -> Path:
    projects = load_project_aliases()
    repo = resolve_project_alias(value, projects)
    if repo is None:
        repo = Path(value).expanduser().resolve()
    repo = ensure_under_dev(repo)
    if not repo.exists() or not repo.is_dir():
        raise PrdViewerError(f"Repo does not exist or is not a directory: {repo}")
    return repo


def drafts_dir(repo: Path) -> Path:
    return repo / DRAFTS_RELATIVE


def content_signature(*parts: str) -> str:
    normalized = "\n".join(part.strip() for part in parts if part and part.strip())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def file_signature(path: Path) -> str:
    digest = hashlib.sha1()
    try:
        digest.update(path.read_bytes())
    except OSError:
        digest.update(str(path.resolve()).lower().encode("utf-8"))
        pass
    return digest.hexdigest()[:16]


def extract_title(markdown_text: str, fallback: str) -> str:
    metadata = parse_frontmatter_light(markdown_text)[0]
    if metadata.get("title"):
        return metadata["title"]
    for line in markdown_text.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1)
    return fallback


def parse_frontmatter_light(markdown_text: str) -> tuple[dict[str, str], str]:
    markdown_text = markdown_text.lstrip("\ufeff")
    lines = markdown_text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return {}, markdown_text
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            metadata: dict[str, str] = {}
            for raw in lines[1:index]:
                if ":" not in raw:
                    continue
                key, value = raw.split(":", 1)
                metadata[key.strip().lower()] = value.strip().strip('"')
            return metadata, "\n".join(lines[index + 1 :]).lstrip()
    return {}, markdown_text


def list_drafts(repo: Path) -> list[Draft]:
    root = drafts_dir(repo)
    if not root.exists():
        return []
    drafts: list[Draft] = []
    for path in root.glob("*.md"):
        if not path.is_file():
            continue
        slug = path.stem.lower()
        if not SLUG_RE.fullmatch(slug):
            continue
        stat = path.stat()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8-sig")
        drafts.append(
            Draft(
                slug=slug,
                markdown_path=path,
                html_path=path.with_suffix(".html"),
                title=extract_title(text, slug),
                modified_at=stat.st_mtime,
                size=stat.st_size,
                signature=file_signature(path),
            )
        )
    return sorted(drafts, key=lambda draft: (draft.modified_at, draft.slug), reverse=True)


def find_draft(repo: Path, slug: str) -> Draft:
    slug = validate_slug(slug)
    path = drafts_dir(repo) / f"{slug}.md"
    if not path.exists() or not path.is_file():
        raise PrdViewerError(f"PRD draft does not exist: {path}")
    drafts = {draft.slug: draft for draft in list_drafts(repo)}
    if slug not in drafts:
        raise PrdViewerError(f"PRD draft is not a valid Markdown draft: {path}")
    return drafts[slug]


def load_renderer(converter: Path = DEFAULT_CONVERTER) -> ModuleType:
    if not converter.exists():
        raise PrdViewerError(f"Markdown converter not found: {converter}")
    spec = importlib.util.spec_from_file_location("prd_viewer_md_to_html", converter)
    if spec is None or spec.loader is None:
        raise PrdViewerError(f"Could not load converter: {converter}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def escape_text(value: object) -> str:
    import html

    return html.escape(str(value), quote=True)


def qs(**params: str) -> str:
    return urllib.parse.urlencode(params)


def format_mtime(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))


def viewer_bar(repo_arg: str, repo: Path, current_slug: str, drafts: list[Draft]) -> str:
    options = []
    for draft in drafts:
        selected = " selected" if draft.slug == current_slug else ""
        options.append(
            f'<option value="{escape_text(draft.slug)}"{selected}>{escape_text(draft.title)} ({escape_text(draft.slug)})</option>'
        )
    list_url = "/?" + qs(repo=repo_arg)
    current = find_draft(repo, current_slug)
    html_link = current.html_path.resolve().as_uri() if current.html_path.exists() else ""
    generated_link = (
        f'<a href="{escape_text(html_link)}" title="Open the generated standalone HTML preview kept for the old file-based workflow">Standalone .html</a>'
        if html_link
        else '<span class="prd-viewer-muted">No standalone .html</span>'
    )
    return f"""
  <form class="prd-viewer-bar" method="get" action="/">
    <input type="hidden" name="repo" value="{escape_text(repo_arg)}">
    <label>
      <span>PRD</span>
      <select name="prd" onchange="this.form.submit()">
        {''.join(options)}
      </select>
    </label>
    <a href="{escape_text(list_url)}">All drafts</a>
    <a href="{escape_text(current.markdown_path.resolve().as_uri())}" title="Open the Markdown source draft">Source .md</a>
    {generated_link}
    <span class="prd-viewer-meta">{escape_text(repo.name)} / {escape_text(current.slug)} / {escape_text(current.signature)}</span>
  </form>
"""


def viewer_css() -> str:
    return """
.prd-viewer-bar {
  align-items: center;
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid #d9e0dd;
  box-shadow: 0 1px 2px rgba(17, 24, 39, 0.06);
  box-sizing: border-box;
  color: #344054;
  display: flex;
  flex-wrap: wrap;
  font-family: Inter, "Segoe UI", system-ui, sans-serif;
  font-size: 12px;
  gap: 10px;
  padding: 7px 14px;
  position: sticky;
  top: 0;
  z-index: 100;
}
.prd-viewer-bar label {
  align-items: center;
  display: flex;
  gap: 8px;
  min-width: 260px;
}
.prd-viewer-bar select {
  background: #fff;
  border: 1px solid #cfd8d3;
  border-radius: 6px;
  color: #172033;
  font: inherit;
  max-width: min(52vw, 620px);
  padding: 4px 8px;
}
.prd-viewer-bar a {
  color: #1769d1;
  font-weight: 700;
  text-decoration: none;
}
.prd-viewer-bar a:hover {
  text-decoration: underline;
}
.prd-viewer-meta,
.prd-viewer-muted {
  color: #667085;
}
.prd-viewer-meta {
  margin-left: auto;
}
body[data-prd-review="true"] .layout {
  grid-template-columns: minmax(0, 1fr) 248px;
}
body[data-prd-review="true"] .outline-panel {
  min-width: 0;
}
@media (max-width: 760px) {
  .prd-viewer-bar {
    align-items: stretch;
  }
  .prd-viewer-bar label,
  .prd-viewer-bar select {
    max-width: none;
    width: 100%;
  }
  .prd-viewer-meta {
    margin-left: 0;
  }
}
@media print {
  .prd-viewer-bar {
    display: none;
  }
}
"""


def render_prd_html(repo_arg: str, repo: Path, slug: str) -> str:
    renderer = load_renderer()
    draft = find_draft(repo, slug)
    raw_markdown_text = draft.markdown_path.read_text(encoding="utf-8")
    metadata, markdown_text = renderer.parse_frontmatter(raw_markdown_text)
    title, source_note, body, outline = renderer.render_markdown(markdown_text)
    if metadata.get("title"):
        title = metadata["title"]
    payload = renderer.build_prd_review_payload(metadata, markdown_text, title, draft.markdown_path)
    if payload.get("isPrdReview"):
        repo_key = metadata.get("repo") or repo.name
        payload["fileUrl"] = draft.markdown_path.resolve().as_uri()
        payload["storageKey"] = content_signature(repo_key, draft.slug, draft.signature)
        payload["viewerUrl"] = f"/?{qs(repo=repo_arg, prd=draft.slug)}"
        payload["sourcePath"] = str(draft.markdown_path)
        payload["contentSignature"] = draft.signature
    html_text = renderer.HTML_TEMPLATE.format(
        title=renderer.escape_text(title),
        heading=renderer.render_inline(title),
        eyebrow=renderer.escape_text("PRD Draft"),
        source=source_note,
        metadata=renderer.render_metadata_panel(metadata),
        body=body,
        outline=outline,
        mobile_outline=outline,
        css=renderer.CSS.strip() + "\n" + viewer_css().strip(),
        has_prd_review="true" if payload.get("isPrdReview") else "false",
        prd_review_json=json.dumps(payload, ensure_ascii=True).replace("</", "<\\/"),
        prd_review_script=renderer.PRD_REVIEW_SCRIPT,
    )
    bar = viewer_bar(repo_arg, repo, draft.slug, list_drafts(repo))
    return html_text.replace("  <div class=\"layout\">", bar + "\n  <div class=\"layout\">", 1)


def render_index_html(repo_arg: str, repo: Path) -> str:
    drafts = list_drafts(repo)
    rows = []
    for draft in drafts:
        view_url = "/?" + qs(repo=repo_arg, prd=draft.slug)
        html_link = draft.html_path.resolve().as_uri() if draft.html_path.exists() else ""
        html_cell = f'<a href="{escape_text(html_link)}">Standalone .html</a>' if html_link else "Not generated"
        rows.append(
            "<tr>"
            f'<td><a href="{escape_text(view_url)}">{escape_text(draft.title)}</a><div>{escape_text(draft.slug)}</div></td>'
            f"<td>{escape_text(format_mtime(draft.modified_at))}</td>"
            f"<td>{escape_text(draft.signature)}</td>"
            f"<td>{html_cell}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="4">No Markdown PRD drafts found.</td></tr>')
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PRD Viewer</title>
  <style>
    body {{
      background: #f5f7f6;
      color: #172033;
      font-family: Inter, "Segoe UI", system-ui, sans-serif;
      margin: 0;
    }}
    main {{
      margin: 0 auto;
      max-width: 1120px;
      padding: 28px 20px 48px;
    }}
    h1 {{
      font-size: 28px;
      margin: 0 0 6px;
    }}
    p {{
      color: #667085;
      margin: 0 0 22px;
    }}
    form {{
      align-items: center;
      display: flex;
      gap: 8px;
      margin: 18px 0 24px;
    }}
    input {{
      border: 1px solid #cfd8d3;
      border-radius: 6px;
      font: inherit;
      padding: 7px 9px;
      width: min(440px, 72vw);
    }}
    button {{
      background: #1769d1;
      border: 0;
      border-radius: 6px;
      color: #fff;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      padding: 8px 12px;
    }}
    table {{
      background: #fff;
      border: 1px solid #e3e8e5;
      border-collapse: collapse;
      width: 100%;
    }}
    th, td {{
      border-bottom: 1px solid #e3e8e5;
      padding: 12px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      color: #667085;
      font-size: 12px;
      text-transform: uppercase;
    }}
    td div {{
      color: #667085;
      font-size: 12px;
      margin-top: 4px;
    }}
    a {{
      color: #1769d1;
      font-weight: 700;
      text-decoration: none;
    }}
    a:hover {{
      text-decoration: underline;
    }}
  </style>
</head>
<body>
  <main>
    <h1>PRD Viewer</h1>
    <p>Repo: {escape_text(repo)}. Markdown remains the source of truth; generated HTML previews are still available when present.</p>
    <form method="get" action="/">
      <label for="repo">Repo</label>
      <input id="repo" name="repo" value="{escape_text(repo_arg)}">
      <button type="submit">Load</button>
    </form>
    <table>
      <thead>
        <tr><th>Draft</th><th>Modified</th><th>Signature</th><th>Standalone</th></tr>
      </thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
  </main>
</body>
</html>
"""


def json_response(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def html_response(handler: BaseHTTPRequestHandler, body_text: str, status: int = 200) -> None:
    body = body_text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def error_response(handler: BaseHTTPRequestHandler, message: str, status: int = 400) -> None:
    html_response(
        handler,
        f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>PRD Viewer Error</title></head>
<body style="font-family:Segoe UI,system-ui,sans-serif;padding:32px">
<h1>PRD Viewer Error</h1><p>{escape_text(message)}</p></body></html>""",
        status,
    )


class PrdViewerHandler(BaseHTTPRequestHandler):
    server_version = "PrdViewer/0.1"

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        repo_arg = params.get("repo", [DEFAULT_REPO])[0] or DEFAULT_REPO
        try:
            if parsed.path == "/health":
                json_response(self, {"ok": True, "service": "prd-viewer"})
                return
            repo = resolve_repo(repo_arg)
            if parsed.path == "/api/prds":
                drafts = list_drafts(repo)
                json_response(
                    self,
                    {
                        "repo": str(repo),
                        "drafts": [
                            {
                                "slug": draft.slug,
                                "title": draft.title,
                                "path": str(draft.markdown_path),
                                "signature": draft.signature,
                                "modifiedAt": draft.modified_at,
                                "hasGeneratedHtml": draft.html_path.exists(),
                            }
                            for draft in drafts
                        ],
                    },
                )
                return
            if parsed.path not in {"/", "/view"}:
                error_response(self, f"Unknown path: {parsed.path}", 404)
                return
            slug = params.get("prd", [""])[0].strip()
            if slug:
                html_response(self, render_prd_html(repo_arg, repo, slug))
            else:
                html_response(self, render_index_html(repo_arg, repo))
        except PrdViewerError as exc:
            error_response(self, str(exc), 400)
        except Exception as exc:  # Keep the tool debuggable instead of hiding render failures.
            error_response(self, f"Unexpected error: {type(exc).__name__}: {exc}", 500)

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))


def health_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/health"


def viewer_url(host: str, port: int, repo: str, slug: str | None = None) -> str:
    params = {"repo": repo}
    if slug:
        params["prd"] = slug
    return f"http://{host}:{port}/?{qs(**params)}"


def is_server_healthy(host: str, port: int, timeout: float = 0.8) -> bool:
    try:
        with urllib.request.urlopen(health_url(host, port), timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def wait_for_server(host: str, port: int, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_server_healthy(host, port):
            return True
        time.sleep(0.2)
    return False


def start_background_server(host: str, port: int) -> int:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    log_path = TMP_ROOT / "prd-viewer.log"
    pid_path = TMP_ROOT / "prd-viewer.pid"
    stdout = log_path.open("a", encoding="utf-8")
    command = [sys.executable, str(Path(__file__).resolve()), "serve", "--host", host, "--port", str(port)]
    creationflags = 0
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
        kwargs["creationflags"] = creationflags
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(
        command,
        cwd=str(APP_ROOT),
        stdout=stdout,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        close_fds=True,
        **kwargs,
    )
    pid_path.write_text(str(process.pid), encoding="utf-8")
    return process.pid


def serve_command(args: argparse.Namespace) -> None:
    server = ThreadingHTTPServer((args.host, args.port), PrdViewerHandler)
    print(f"PRD viewer listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


def open_command(args: argparse.Namespace) -> None:
    repo = resolve_repo(args.repo)
    if args.prd:
        find_draft(repo, args.prd)
    started_pid = None
    if not is_server_healthy(args.host, args.port):
        started_pid = start_background_server(args.host, args.port)
        if not wait_for_server(args.host, args.port):
            raise PrdViewerError(f"Started server pid {started_pid}, but health check did not pass.")
    url = viewer_url(args.host, args.port, args.repo, args.prd)
    print(url)
    if started_pid:
        print(f"Started PRD viewer pid {started_pid}. Logs: {TMP_ROOT / 'prd-viewer.log'}")
    if not args.no_browser:
        webbrowser.open(url)


def list_command(args: argparse.Namespace) -> None:
    repo = resolve_repo(args.repo)
    drafts = list_drafts(repo)
    if not drafts:
        print(f"No PRD drafts found under {drafts_dir(repo)}")
        return
    for draft in drafts:
        print(f"{draft.slug}\t{format_mtime(draft.modified_at)}\t{draft.title}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone local PRD Markdown viewer.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run the local viewer server in the foreground.")
    serve.add_argument("--host", default=DEFAULT_HOST)
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.set_defaults(func=serve_command)

    open_parser = subparsers.add_parser("open", help="Start the viewer if needed, then open a PRD or draft list.")
    open_parser.add_argument("prd", nargs="?", help="Optional PRD slug to open.")
    open_parser.add_argument("--repo", default=DEFAULT_REPO, help="Repo alias or path. Default: current directory.")
    open_parser.add_argument("--host", default=DEFAULT_HOST)
    open_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    open_parser.add_argument("--no-browser", action="store_true", help="Print the URL without opening a browser.")
    open_parser.set_defaults(func=open_command)

    list_parser = subparsers.add_parser("list", help="List local PRD Markdown drafts for a repo.")
    list_parser.add_argument("--repo", default=DEFAULT_REPO, help="Repo alias or path. Default: current directory.")
    list_parser.set_defaults(func=list_command)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except PrdViewerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
