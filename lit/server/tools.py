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
chapters of text. Each user has libraries: lists of papers from the collection.
Your own library is the default scope of every tool; name another with
`library`, or give `scope` explicitly (`disk` is the whole collection).

Start with `papers` to see what a library holds, then `toc` for one paper and
`show` to read an address that `toc` or `search` gave you. An address is
`<slug>`, `<slug>/<chapter>`, or `<slug>/<chapter>#<anchor>`.

Reports live on the server, under a name you choose. Keep a research log while
you research: `append_log` one entry after each step (what you searched, what
you read, what stayed open). Write the report with `write_report`, citing a
place as ([§2](lit:<slug>/<chapter>#<anchor>)). Fix it with `edit_report`,
which changes one passage: never send the whole report again to fix a detail.
Then run `check_report`, fix what it lists, and run `render_report`, which
gives the link to the rendered report that you hand to the user.
"""


def caller(ctx: Context, root: Path) -> str:
    """The user whose bearer token this request carries."""
    request = ctx.request_context.request  # the Starlette request, over HTTP
    headers = request.headers if request is not None else {}
    scheme, _, token = (headers.get("authorization") or "").partition(" ")
    with state.connect(root) as db:
        user = state.user_for(db, token.strip()) if scheme.lower() == "bearer" else None
    if user is None:
        raise ToolError("no valid bearer token")
    return user


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


# The parts of a report, as an agent names them, and the columns that hold them.
PARTS = {"report": "text", "log": "log"}


def build(root: Path, base_url: str, wake) -> MCPServer:
    """The MCP server for one collection. `wake` starts the ingest worker."""
    mcp = MCPServer("literature", instructions=INSTRUCTIONS)

    def scope_of(user: str, library: str | None, scope: list[str] | None) -> list[str]:
        if scope:
            return scope
        name = library or user
        with state.connect(root) as db:
            if not state.library_exists(db, name):
                raise ToolError("there is no library named %s" % name)
            held = set(paths.papers_on_disk(root))
            slugs = [slug for slug in state.library_slugs(db, name) if slug in held]
        if not slugs:  # an empty --scope would mean the whole collection
            raise ToolError("the library %s lists no papers yet; add some, or pass scope=['disk']" % name)
        return slugs

    @mcp.tool()
    async def libraries(ctx: Context) -> dict:
        """Every library: its name, owner and number of papers, and which one is yours."""
        user = caller(ctx, root)
        with state.connect(root) as db:
            rows = [dict(row) for row in state.libraries(db)]
        return {"you": user, "default_library": user, "libraries": rows}

    @mcp.tool()
    async def papers(ctx: Context, library: str | None = None) -> dict:
        """The papers a library lists (default: yours), with slug, title, authors and year."""
        user = caller(ctx, root)
        found = []
        for slug in scope_of(user, library, None):
            paper = paths.read_paper(root, slug)
            found.append({"slug": slug, "title": paper.get("title"), "year": paper.get("year"),
                          "authors": (paper.get("authors") or [])[:3]})
        return {"library": library or user, "papers": found}

    @mcp.tool()
    async def search(ctx: Context, phrase: str, library: str | None = None,
                     scope: list[str] | None = None, approx: bool = False,
                     context: int = 0, max_results: int = 20) -> dict:
        """Find a phrase in the text of the papers, and give the address of every block that matches.

        Exact by default, with whitespace and quotation marks normalised; when the
        phrase matches nothing, `partial_matches` gives the longest shorter phrase
        that does. `approx` ranks blocks by meaning instead, and needs a scope
        narrower than `disk`. `context` adds N neighbouring blocks to each hit,
        which is how an equation next to a matching sentence reaches you.
        """
        user = caller(ctx, root)
        args = ["--scope", *scope_of(user, library, scope),
                "--context=%d" % context, "--max-results=%d" % max_results]
        return await litdb(root, "search", *args, *(["--approx"] if approx else []), "--", phrase)

    @mcp.tool()
    async def show(ctx: Context, address: str, context: int = 0, anchors_only: bool = False,
                   max_words: int = 2000) -> dict:
        """Read what stands at an address: a block, a span, a section or a whole chapter."""
        caller(ctx, root)
        args = ["--context=%d" % context, "--max-words=%d" % max_words]
        return await litdb(root, "show", *args, *(["--anchors-only"] if anchors_only else []),
                           "--", address)

    @mcp.tool()
    async def toc(ctx: Context, slug: str, depth: int = 2, all_anchors: bool = False) -> dict:
        """What a paper is (title, authors, abstract, publication) and every chapter and section, with addresses and word counts."""
        caller(ctx, root)
        return await litdb(root, "toc", "--depth=%d" % depth,
                           *(["--all-anchors"] if all_anchors else []), "--", slug)

    @mcp.tool()
    async def lookup(ctx: Context, tags: list[str] | None = None, search: str | None = None,
                     doi: str | None = None, arxiv: str | None = None,
                     cited_by: str | None = None) -> dict:
        """What the collection knows about a cited work: by citation tag, by DOI or arXiv id, by a substring of its title or authors, or every work a paper cites (`cited_by=<slug>`)."""
        caller(ctx, root)
        args = ["--%s=%s" % (name, value) for name, value in
                (("search", search), ("doi", doi), ("arxiv", arxiv), ("cited-by", cited_by)) if value]
        return await litdb(root, "lookup", *args, "--", *(tags or []))

    @mcp.tool()
    async def citations(ctx: Context, arxiv_id: str, direction: str = "citing",
                        sort: str = "mostcited", max_results: int = 20) -> dict:
        """The papers that cite a paper (`citing`), the works it draws on (`cited`), or `both`, from INSPIRE-HEP. Marks the ones the collection holds."""
        caller(ctx, root)
        return await litdb(root, "citations", "--direction=%s" % direction, "--sort=%s" % sort,
                           "--max-results=%d" % max_results, "--", arxiv_id)

    @mcp.tool()
    async def find(ctx: Context, topic: str, categories: list[str] | None = None,
                   since: int | None = None, max_results: int = 15, kind: str = "any",
                   sort: str = "relevance") -> dict:
        """Search arXiv abstracts for a subject, ranked against it, and mark the papers the collection holds. Write the topic as a full phrase. Takes several seconds."""
        caller(ctx, root)
        args = ["--topic=%s" % topic, "--max-results=%d" % max_results, "--kind=%s" % kind,
                "--sort=%s" % sort, *["--category=%s" % c for c in categories or []]]
        return await litdb(root, "find", *args, *(["--since=%d" % since] if since else []))

    @mcp.tool()
    async def add(ctx: Context, arxiv_ids: list[str], library: str | None = None) -> dict:
        """Add papers to a library (default: yours) by arXiv identifier.

        A paper the collection holds is listed at once. Any other is queued for
        ingest, which takes minutes; poll `ingest_status` with the job id.
        """
        user = caller(ctx, root)
        results = []
        with state.connect(root) as db:
            for argument in arxiv_ids:
                try:
                    outcome, what = state.add_paper(db, root, argument, library or user, user)
                except ValueError as error:
                    outcome, what = "refused", str(error)
                results.append({"arxiv_id": argument, "outcome": outcome,
                                ("slug" if outcome == "listed" else "job" if outcome == "queued"
                                 else "error"): what})
        wake()
        return {"library": library or user, "results": results}

    @mcp.tool()
    async def ingest_status(ctx: Context, job: int | None = None) -> dict:
        """The state of one ingest job (queued, running, done or failed), or of your 20 most recent."""
        user = caller(ctx, root)
        with state.connect(root) as db:
            if job is not None:
                found = state.job(db, job)
                return {"jobs": [found] if found else []}
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
