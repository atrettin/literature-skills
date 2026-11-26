"""The MCP endpoint: the `litdb` commands, for an agent that holds no collection.

Each read tool runs the command an agent with a local collection would run, and
returns the JSON it prints, with its exit status as `exit`: the skills document
that JSON and those statuses, and this keeps them true over MCP.

The caller is the user whose token the request carries, and their personal
library is the default scope. A library is a list of slugs, so it becomes
`--scope <slug> …`; an agent names `disk` to search the whole collection.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from lit import check_report, paths, render_report
from lit.server import state

INSTRUCTIONS = """\
A shared collection of scientific papers, converted from their arXiv TeX into
chapters of text, with libraries: lists of papers from the collection.

The tools are the `litdb` commands the literature skills describe, under the
same names: `litdb X --some-opt v` is the tool `X(some_opt=v)`, and the `exit`
field of the answer is the exit status. `--scope` becomes `scope`, or
`library` to search a library; the default library is the project's
(`LITERATURE_LIBRARY`) or else yours, and `libraries` says which;
`create_library` starts a new one. `find` finds a paper, by subject or by
title; `add` adds one whose arXiv identifier `find` gave. There are no files here: read a paper with
`toc`, then `show`. Reports and research logs
live on the server: `append_log`, `write_report`, `edit_report`,
`check_report`, `render_report`.
"""


def headers_of(ctx: Context):
    request = ctx.request_context.request  # the Starlette request, over HTTP
    return request.headers if request is not None else {}


def caller(ctx: Context, root: Path) -> str:
    """The user whose bearer token this request carries."""
    headers = headers_of(ctx)
    scheme, _, token = (headers.get("authorization") or "").partition(" ")
    with state.connect(root) as db:
        user = state.user_for(db, token.strip()) if scheme.lower() == "bearer" else None
    if user is None:
        raise ToolError("no valid bearer token")
    if project_library(ctx) == state.LOCAL:
        raise ToolError("this project works on its local collection (LITERATURE_LIBRARY=local); "
                        "use `litdb` there, not the literature server")
    return user


def project_library(ctx: Context) -> str:
    """The library the project chose with LITERATURE_LIBRARY, which its MCP client sends."""
    return (headers_of(ctx).get("x-literature-library") or "").strip()


def default_library(ctx: Context, user: str) -> str:
    return project_library(ctx) or user


async def litdb(root: Path, command: str, *args: str) -> dict:
    """Run one `litdb` command, and return its JSON with its exit status."""
    done = await anyio.run_process(
        [sys.executable, "-m", "lit", command, "--literature-root", str(root), *args],
        check=False,
    )
    try:
        report = json.loads(done.stdout)
    except json.JSONDecodeError:
        report = {"error": (done.stderr or done.stdout).decode(errors="replace").strip()[-2000:]}
    return {"exit": done.returncode, **report} if isinstance(report, dict) else {
        "exit": done.returncode, "result": report}


def named(arxiv_id: str | None, doi: str | None, recid: str | None) -> list[str]:
    """A paper named by arXiv id, DOI or INSPIRE record, as the commands take it."""
    return [*(["--doi=%s" % doi] if doi else []), *(["--recid=%s" % recid] if recid else []),
            *(["--", arxiv_id] if arxiv_id else [])]


# The longest an `ingest_status` call waits for a job. Below the proxy's read
# timeout, and long enough that a ten-minute ingest takes two or three calls.
MAX_WAIT_S = 300

# The parts of a report, as an agent names them, and the columns that hold them.
PARTS = {"report": "text", "log": "log"}


def build(root: Path, base_url: str, wake) -> MCPServer:
    """The MCP server for one collection. `wake` starts the ingest worker."""
    mcp = MCPServer("literature", instructions=INSTRUCTIONS)

    def scope_of(ctx: Context, user: str, library: str | None,
                 scope: list[str] | None) -> list[str]:
        if scope:
            return scope
        name = library or default_library(ctx, user)
        with state.connect(root) as db:
            if not state.library_exists(db, name):
                origin = "" if library or not project_library(ctx) else " (from LITERATURE_LIBRARY)"
                raise ToolError("there is no library named %s%s" % (name, origin))
            held = set(paths.papers_on_disk(root))
            slugs = [slug for slug in state.library_slugs(db, name) if slug in held]
        if not slugs:  # an empty --scope would mean the whole collection
            raise ToolError("the library %s lists no papers yet; add some, or pass scope=['disk']" % name)
        return slugs

    @mcp.tool()
    async def libraries(ctx: Context) -> dict:
        """Every library: its name, owner and number of papers; which one is yours, and which is the default and who chose it (the project's LITERATURE_LIBRARY, or your personal one)."""
        user = caller(ctx, root)
        with state.connect(root) as db:
            rows = [dict(row) for row in state.libraries(db)]
        return {"you": user, "default_library": default_library(ctx, user),
                "chosen_by": "project" if project_library(ctx) else "personal", "libraries": rows}

    @mcp.tool()
    async def create_library(ctx: Context, name: str) -> dict:
        """Create an empty library that you own; fill it with `add`. A name is letters, digits, - and _."""
        user = caller(ctx, root)
        with state.connect(root) as db:
            try:
                state.create_library(db, name, user)
            except ValueError as error:
                raise ToolError(str(error))
            except sqlite3.IntegrityError:
                raise ToolError("a library named %s exists already" % name)
        return {"library": name, "owner": user}

    @mcp.tool()
    async def papers(ctx: Context, library: str | None = None) -> dict:
        """The papers a library lists (default: the default library), with slug, title, authors and year."""
        user = caller(ctx, root)
        found = []
        for slug in scope_of(ctx, user, library, None):
            paper = paths.read_paper(root, slug)
            found.append({"slug": slug, "title": paper.get("title"), "year": paper.get("year"),
                          "authors": (paper.get("authors") or [])[:3]})
        return {"library": library or default_library(ctx, user), "papers": found}

    @mcp.tool()
    async def search(ctx: Context, phrase: str, library: str | None = None,
                     scope: list[str] | None = None, approx: bool = False, regex: bool = False,
                     context: int = 0, max_results: int = 20) -> dict:
        """Find a phrase in the text of the papers, and give the address of every block that matches.

        Exact by default, with whitespace and quotation marks normalised; when the
        phrase matches nothing, `partial_matches` gives the longest shorter phrase
        that does. `approx` ranks blocks by meaning instead, and needs a scope
        narrower than `disk`. `context` adds N neighbouring blocks to each hit,
        which is how an equation next to a matching sentence reaches you.
        """
        user = caller(ctx, root)
        args = ["--scope", *scope_of(ctx, user, library, scope),
                "--context=%d" % context, "--max-results=%d" % max_results,
                *(["--approx"] if approx else []), *(["--regex"] if regex else [])]
        return await litdb(root, "search", *args, "--", phrase)

    @mcp.tool()
    async def show(ctx: Context, target: str, context: int = 0, anchors_only: bool = False,
                   max_words: int = 2000) -> dict:
        """Read what stands at an address (`target`): a block, a span, a section or a whole chapter. When `max_words` cuts the answer, it says the anchor to resume from."""
        caller(ctx, root)
        args = ["--context=%d" % context, "--max-words=%d" % max_words]
        return await litdb(root, "show", *args, *(["--anchors-only"] if anchors_only else []),
                           "--", target)

    @mcp.tool()
    async def toc(ctx: Context, slug: str, depth: int = 2, all_anchors: bool = False) -> dict:
        """What a paper is (title, authors, abstract, publication) and every chapter and section, with addresses and word counts."""
        caller(ctx, root)
        return await litdb(root, "toc", "--depth=%d" % depth,
                           *(["--all-anchors"] if all_anchors else []), "--", slug)

    @mcp.tool()
    async def lookup(ctx: Context, tags: list[str] | None = None, search: str | None = None,
                     doi: str | None = None, arxiv: str | None = None,
                     cited_by: str | None = None, all_authors: bool = False) -> dict:
        """What the collection knows about a cited work: by citation tag, by DOI or arXiv id, by a substring of its title or authors, or every work a paper cites (`cited_by=<slug>`)."""
        caller(ctx, root)
        args = ["--%s=%s" % (name, value) for name, value in
                (("search", search), ("doi", doi), ("arxiv", arxiv), ("cited-by", cited_by)) if value]
        args += ["--all-authors"] if all_authors else []
        return await litdb(root, "lookup", *args, "--", *(tags or []))

    @mcp.tool()
    async def citations(ctx: Context, arxiv_id: str | None = None, doi: str | None = None,
                        recid: str | None = None, direction: str = "citing",
                        sort: str = "mostcited", max_results: int = 20) -> dict:
        """The papers that cite a paper (`citing`), the works it draws on (`cited`), or `both`, from INSPIRE-HEP. Marks the ones the collection holds."""
        caller(ctx, root)
        return await litdb(root, "citations", "--direction=%s" % direction, "--sort=%s" % sort,
                           "--max-results=%d" % max_results, *named(arxiv_id, doi, recid))

    @mcp.tool()
    async def overlap(ctx: Context, arxiv_id: str | None = None, doi: str | None = None,
                      recid: str | None = None, library: str | None = None,
                      scope: list[str] | None = None, resolve: bool = False) -> dict:
        """How much a candidate paper adds to a library (default: the default library): which of its references and citers the library already holds. Uses INSPIRE-HEP."""
        user = caller(ctx, root)
        return await litdb(root, "overlap", "--scope", *scope_of(ctx, user, library, scope),
                           *(["--resolve"] if resolve else []), *named(arxiv_id, doi, recid))

    @mcp.tool()
    async def terminology(ctx: Context, topic: str, library: str | None = None,
                          scope: list[str] | None = None, corpus: str = "both") -> dict:
        """The other names the papers of a library use for a subject, with where each one occurs."""
        user = caller(ctx, root)
        return await litdb(root, "terminology", "--topic=%s" % topic, "--corpus=%s" % corpus,
                           "--scope", *scope_of(ctx, user, library, scope))

    @mcp.tool()
    async def find(ctx: Context, topic: str | None = None, title: str | None = None,
                   author: str | None = None, year: int | None = None,
                   category: list[str] | None = None, since: int | None = None,
                   max_results: int = 15, kind: str = "any", sort: str = "relevance",
                   full: bool = False) -> dict:
        """Find papers on arXiv, and mark the ones the collection holds. Takes several seconds.

        Two modes. `topic`: a subject, written as a full phrase, ranked against
        the abstracts. `title` (with `author`, `year`): one paper you can name,
        even by part of its title; `match` says how well the hits agree. Use this
        to settle a paper's identity before `add`. `full` gives every field.
        """
        caller(ctx, root)
        args = ["--max-results=%d" % max_results, *(["--full"] if full else [])]
        if topic is not None:
            args += ["--topic=%s" % topic, "--kind=%s" % kind, "--sort=%s" % sort,
                     *["--category=%s" % c for c in category or []],
                     *(["--since=%d" % since] if since else [])]
        args += [*(["--title=%s" % title] if title else []),
                 *(["--author=%s" % author] if author else []),
                 *(["--year=%d" % year] if year else [])]
        return await litdb(root, "find", *args)

    @mcp.tool()
    async def add(ctx: Context, arxiv_ids: list[str], library: str | None = None) -> dict:
        """Add papers to a library (default: the default library) by arXiv identifier.

        Only for a paper whose identity is settled: find its identifier with
        `find` first (`title` for a paper you can name). A paper the collection holds is listed at once. Any other is queued for
        ingest, which takes minutes; poll `ingest_status` with the job id.
        """
        user = caller(ctx, root)
        results = []
        with state.connect(root) as db:
            for argument in arxiv_ids:
                try:
                    outcome, what = state.add_paper(db, root, argument,
                                                    library or default_library(ctx, user), user)
                except ValueError as error:
                    outcome, what = "refused", str(error)
                results.append({"arxiv_id": argument, "outcome": outcome,
                                ("slug" if outcome == "listed" else "job" if outcome == "queued"
                                 else "error"): what})
        wake()
        return {"library": library or default_library(ctx, user), "results": results}

    @mcp.tool()
    async def ingest_status(ctx: Context, job: int | None = None, wait: int = 0) -> dict:
        """The state of one ingest job (queued, running, done or failed), or of your 20 most recent. With `job`, `wait` waits up to that many seconds (at most 300) for the job to finish, so one call replaces many polls."""
        user = caller(ctx, root)
        if job is not None:
            deadline = anyio.current_time() + min(max(wait, 0), MAX_WAIT_S)
            while True:
                with state.connect(root) as db:
                    found = state.job(db, job)
                if not found or found["status"] in ("done", "failed") \
                        or anyio.current_time() >= deadline:
                    return {"jobs": [found] if found else []}
                await anyio.sleep(2)
        with state.connect(root) as db:
            rows = [row for row in state.jobs(db) if row["user"] == user][:20]
        return {"jobs": rows}

    def own_report(user: str, name: str):
        with state.connect(root) as db:
            found = state.report(db, user, name)
        if found is None:
            raise ToolError("you have no report named %s" % name)
        return found

    def written(user: str, name: str, text: str) -> dict:
        return {"report": name, "words": len(text.split()),
                "url": "%s/reports/%s/%s" % (base_url.rstrip("/"), user, name)}

    @mcp.tool()
    async def write_report(ctx: Context, name: str, text: str, part: str = "report") -> dict:
        """Create a report of yours, or replace its whole text (`part="report"`) or research log (`part="log"`). Send the full text once; fix it afterwards with `edit_report`."""
        user = caller(ctx, root)
        with state.connect(root) as db:
            try:
                state.write_report(db, user, name, PARTS.get(part, part), text)
            except ValueError as error:
                raise ToolError(str(error))
        return written(user, name, text)

    @mcp.tool()
    async def append_log(ctx: Context, name: str, entry: str) -> dict:
        """Add one entry to the end of a report's research log, creating the report if it does not exist yet."""
        user = caller(ctx, root)
        with state.connect(root) as db:
            try:
                log = state.append_log(db, user, name, entry)
            except ValueError as error:
                raise ToolError(str(error))
        return written(user, name, log)

    @mcp.tool()
    async def edit_report(ctx: Context, name: str, old_text: str, new_text: str,
                          part: str = "report") -> dict:
        """Replace one passage of a report (or of its log, `part="log"`). `old_text` must occur exactly once; give enough of it to be unique."""
        user = caller(ctx, root)
        with state.connect(root) as db:
            try:
                text = state.edit_report(db, user, name, PARTS.get(part, part), old_text, new_text)
            except (LookupError, ValueError) as error:
                raise ToolError(str(error))
        return written(user, name, text)

    @mcp.tool()
    async def read_report(ctx: Context, name: str, part: str = "report") -> dict:
        """The source text of a report of yours, or of its log. Read it only when you need to see it again: it costs its full length."""
        found = own_report(caller(ctx, root), name)
        if part not in PARTS:
            raise ToolError("a report has the parts report and log, not %r" % part)
        return {"report": name, "part": part, "text": found[PARTS[part]]}

    @mcp.tool(name="check_report")
    async def check_report_tool(ctx: Context, name: str) -> dict:
        """Check that every `lit:` citation in a report of yours names text the collection holds, that its references match its citations, and that it has a research log."""
        found = own_report(caller(ctx, root), name)
        with tempfile.TemporaryDirectory() as scratch:
            source = Path(scratch) / ("report" + render_report.SOURCE_SUFFIX)
            source.write_text(found["text"], encoding="utf-8")
            if found["log"].strip():
                log = Path(scratch) / ("report" + render_report.LOG_SOURCE_SUFFIX)
                log.write_text(found["log"], encoding="utf-8")
            report = check_report.check(source, root)
        del report["report"], report["literature_root"]  # paths of the scratch copy
        report["research_log"] = bool(found["log"].strip())
        report["broken_markers_in_log"] = check_report.check_markers(
            check_report.markers_in(found["log"]), root)
        report["ok"] = report["ok"] and not report["broken_markers_in_log"]
        return report

    @mcp.tool(name="render_report")
    async def render_report_tool(ctx: Context, name: str) -> dict:
        """The link to the rendered report, where every `lit:` marker opens the place it cites in the server's reader. Lists the markers that resolve to nothing."""
        user = caller(ctx, root)
        found = own_report(user, name)
        collection = render_report.Collection(root, paths.flavor(root))
        unresolved = set()
        for part in PARTS.values():
            unresolved.update(render_report.render_text(found[part], collection, root)[1])
        url = "%s/reports/%s/%s" % (base_url.rstrip("/"), user, name)
        return {"url": url, "log": url + "?part=log", "download": url + ".md",
                "unresolved": sorted(unresolved)}

    return mcp


class BearerGuard:
    """Refuses an MCP request without a known token before the SDK reads it."""

    def __init__(self, app: Any, root: Path) -> None:
        self.app, self.root = app, root

    async def __call__(self, scope, receive, send):
        headers = dict(scope.get("headers") or [])
        scheme, _, token = headers.get(b"authorization", b"").decode().partition(" ")
        with state.connect(self.root) as db:
            user = state.user_for(db, token.strip()) if scheme.lower() == "bearer" else None
        if user is None:
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"text/plain"),
                                    (b"www-authenticate", b"Bearer")]})
            await send({"type": "http.response.body", "body": b"A bearer token is required.\n"})
            return
        await self.app(scope, receive, send)
