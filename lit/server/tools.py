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

In a report, cite a place as ([§2](lit:<slug>/<chapter>#<anchor>)), then run
`check_report` and `render_report` on the text. The rendered report links to
the server's reader.
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

    @mcp.tool(name="check_report")
    async def check_report_text(ctx: Context, text: str) -> dict:
        """Check that every `lit:` citation in a report names text the collection holds."""
        caller(ctx, root)
        with tempfile.TemporaryDirectory() as scratch:
            source = Path(scratch) / "report.source.md"
            source.write_text(text, encoding="utf-8")
            return check_report.check(source, root)

    @mcp.tool(name="render_report")
    async def render_report_text(ctx: Context, text: str) -> dict:
        """Turn the `lit:` markers of a report into links to the server's reader. Unresolved markers are left as they are and listed."""
        caller(ctx, root)
        collection = render_report.Collection(root, paths.flavor(root))
        rendered, unresolved = render_report.render_text(
            text, collection, root, base=base_url.rstrip("/") + "/lit")
        return {"text": rendered, "unresolved": sorted(set(unresolved))}

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
