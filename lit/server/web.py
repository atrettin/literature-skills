"""The web pages: sign in, the list of papers, and the reader.

The reader serves the collection's own `vscode` render. A chapter there is
Markdown with `<a id>` anchors and relative links (`../../references/x.md`,
`03_results.md#eq-4`), so serving the rendered tree at `/lit/<path>` and turning
each `.md` into HTML on request keeps every link working without rewriting one.
The maths stays TeX in the page and KaTeX draws it in the browser.

The text of a paper comes from arXiv and is written by its authors, not by us.
The Content-Security-Policy below therefore runs no script but our own file and
KaTeX's, so a `<script>` that made it through a conversion runs nowhere.
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path

from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from lit import paths
from lit.server import state

HERE = Path(__file__).parent
COOKIE = "litdb_token"

# What the reader serves besides chapters. No PDF, no TeX: the original paper
# is linked at arXiv, never redistributed from here.
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}

CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "font-src https://cdn.jsdelivr.net; "
    "img-src 'self' data:"
)

templates = Jinja2Templates(directory=HERE / "templates")
markdown = (
    MarkdownIt("commonmark", {"html": True})
    .use(dollarmath_plugin, double_inline=True)
    .enable("table")
)


def page(request: Request, name: str, user: str | None, **context) -> Response:
    """A template, given the prefix every link it writes starts with."""
    base = request.scope.get("root_path", "")
    return templates.TemplateResponse(request, name, {"base": base, "user": user, **context})


def signed_in(handler):
    """Run the handler for a known user, and send anyone else to sign in."""

    async def wrapped(request: Request) -> Response:
        with state.connect(request.app.state.root) as db:
            user = state.user_for(db, request.cookies.get(COOKIE))
        if user is None:
            return RedirectResponse(request.scope.get("root_path", "") + "/login", status_code=303)
        return await handler(request, user)

    return wrapped


async def login(request: Request) -> Response:
    base = request.scope.get("root_path", "")
    if request.method == "GET":
        return page(request, "login.html", None, error=None)
    token = str((await request.form()).get("token", "")).strip()
    with state.connect(request.app.state.root) as db:
        user = state.user_for(db, token)
    if user is None:
        return page(request, "login.html", None, error="That token is not known.")
    response = RedirectResponse(base + "/", status_code=303)
    response.set_cookie(COOKIE, token, max_age=365 * 24 * 3600, path=base or "/",
                        httponly=True, samesite="lax")
    return response


async def logout(request: Request) -> Response:
    base = request.scope.get("root_path", "")
    response = RedirectResponse(base + "/login", status_code=303)
    response.delete_cookie(COOKIE, path=base or "/")
    return response


def short_authors(authors: list[str]) -> str:
    return ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")


def paper_rows(root: Path, slugs: list[str]) -> list[dict]:
    rows = []
    for slug in slugs:
        if not paths.paper_path(root, slug).is_file():
            continue  # listed in a library, and since removed from the collection
        paper = paths.read_paper(root, slug)
        rows.append({
            "slug": slug,
            "title": paper.get("title") or slug,
            "authors": short_authors(paper.get("authors") or []),
            "year": paper.get("year") or "",
        })
    rows.sort(key=lambda row: (-int(row["year"] or 0), row["title"].lower()))
    return rows


@signed_in
async def papers(request: Request, user: str) -> Response:
    root: Path = request.app.state.root
    library = request.query_params.get("library", "")
    with state.connect(root) as db:
        everything = state.libraries(db)
        if library and not state.library_exists(db, library):
            return message(request, user, "There is no library named %s." % library, 404)
        slugs = state.library_slugs(db, library) if library else paths.papers_on_disk(root)
        admin = state.is_admin(db, user)
    return page(request, "papers.html", user, papers=paper_rows(root, slugs),
                libraries=everything, library=library, admin=admin)


@signed_in
async def remove_paper(request: Request, user: str) -> Response:
    """An admin takes a paper out of the collection, and so out of every library."""
    root: Path = request.app.state.root
    form = await request.form()
    slug, force = str(form.get("slug", "")), bool(form.get("force"))
    with state.connect(root) as db:
        if not state.is_admin(db, user):
            return message(request, user, "Only an administrator removes papers from the collection.", 403)
        if not state.WRITE_LOCK.acquire(blocking=False):
            return message(request, user, "An ingest is running. Try again when it has finished.", 409)
        try:
            code, report = state.remove_paper(db, root, slug, force)
        finally:
            state.WRITE_LOCK.release()
    if code == 2 and report.get("cited_by"):
        return page(request, "remove.html", user, slug=slug, cited_by=report["cited_by"])
    if code != 0:
        return message(request, user, report.get("error") or "The paper was not removed.",
                       404 if code == 1 else 400)
    return RedirectResponse(request.scope.get("root_path", "") + "/", status_code=303)


def message(request: Request, user: str | None, text: str, status: int = 400) -> Response:
    response = page(request, "message.html", user, text=text)
    response.status_code = status
    return response


def back_to(request: Request, library: str) -> Response:
    base = request.scope.get("root_path", "")
    return RedirectResponse("%s/?library=%s" % (base, library), status_code=303)


@signed_in
async def library_list(request: Request, user: str) -> Response:
    with state.connect(request.app.state.root) as db:
        everything = state.libraries(db)
    return page(request, "libraries.html", user, libraries=everything)


@signed_in
async def delete_library(request: Request, user: str) -> Response:
    name = str((await request.form()).get("name", ""))
    with state.connect(request.app.state.root) as db:
        try:
            state.delete_library(db, name, user)
        except LookupError as error:
            return message(request, user, str(error), 404)
        except PermissionError as error:
            return message(request, user, str(error), 403)
    return RedirectResponse(request.scope.get("root_path", "") + "/libraries", status_code=303)


@signed_in
async def create_library(request: Request, user: str) -> Response:
    name = str((await request.form()).get("name", "")).strip()
    with state.connect(request.app.state.root) as db:
        try:
            state.create_library(db, name, user)
        except ValueError as error:
            return message(request, user, str(error))
        except sqlite3.IntegrityError:
            return message(request, user, "A library named %s exists already." % name)
    return RedirectResponse(request.scope.get("root_path", "") + "/libraries", status_code=303)


@signed_in
async def list_in_library(request: Request, user: str) -> Response:
    """Add a paper the collection holds to a library, or take it out again."""
    root: Path = request.app.state.root
    form = await request.form()
    library, slug = str(form.get("library", "")), str(form.get("slug", ""))
    with state.connect(root) as db:
        action = request.path_params["action"]
        if action not in ("add", "remove") or not state.library_exists(db, library):
            return message(request, user, "There is no library named %s." % library, 404)
        if action == "remove":
            state.remove_from_library(db, library, slug)
        elif paths.paper_path(root, slug).is_file():
            state.add_to_library(db, library, slug, user)
        else:
            return message(request, user, "The collection holds no paper %s." % slug, 404)
    return back_to(request, library)


@signed_in
async def add(request: Request, user: str) -> Response:
    """Add papers by arXiv identifier. A paper already held is listed at once."""
    root: Path = request.app.state.root
    with state.connect(root) as db:
        everything = state.libraries(db)
    if request.method == "GET":
        return page(request, "add.html", user, libraries=everything, library=user, results=[])
    form = await request.form()
    library = str(form.get("library", user))
    results = []
    with state.connect(root) as db:
        for argument in str(form.get("ids", "")).replace(",", " ").split():
            try:
                outcome, what = state.add_paper(db, root, argument, library, user)
            except ValueError as error:
                outcome, what = "refused", str(error)
            results.append({"argument": argument, "outcome": outcome, "what": what})
    worker = request.app.state.worker
    if worker is not None and any(r["outcome"] == "queued" for r in results):
        worker.wake.set()
    return page(request, "add.html", user, libraries=everything, library=library, results=results)


@signed_in
async def jobs(request: Request, user: str) -> Response:
    status = request.query_params.get("status") or None
    with state.connect(request.app.state.root) as db:
        rows = state.jobs(db, status)
        admin = state.is_admin(db, user)
    busy = any(row["status"] in ("queued", "running") for row in rows)
    return page(request, "jobs.html", user, jobs=rows, status=status, admin=admin, busy=busy)


@signed_in
async def retry(request: Request, user: str) -> Response:
    """Queue a failed ingest again. Only an administrator may force it."""
    form = await request.form()
    with state.connect(request.app.state.root) as db:
        force = bool(form.get("force")) and state.is_admin(db, user)
        state.retry(db, int(request.path_params["id"]), force)
    worker = request.app.state.worker
    if worker is not None:
        worker.wake.set()
    return RedirectResponse(request.scope.get("root_path", "") + "/jobs", status_code=303)


def resolve(root: Path, relative: str) -> Path | None:
    """The file under the root that a reader path names, or None.

    A dot-file is never served: the collection keeps its state in them, the
    server's users among it. Neither is anything outside the root.
    """
    parts = Path(relative).parts
    if not parts or any(part.startswith(".") for part in parts):
        return None
    target = (root / relative).resolve()
    if root.resolve() not in target.parents or not target.is_file():
        return None
    return target


def title_of(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


@signed_in
async def reader(request: Request, user: str) -> Response:
    root: Path = request.app.state.root
    relative = request.path_params["path"]
    target = resolve(root, relative)
    if target is None:
        return PlainTextResponse("Not found.", status_code=404)
    if target.suffix in IMAGES:
        return FileResponse(target)
    if target.suffix != ".md":
        return PlainTextResponse("Not found.", status_code=404)
    text = target.read_text(encoding="utf-8")
    slug = Path(relative).parts[0]
    contents = slug if paths.paper_path(root, slug).is_file() else None
    libraries = []
    if contents and relative == "%s/%s" % (slug, paths.INDEX_NAME):
        with state.connect(root) as db:
            libraries = state.libraries(db)
    return page(request, "reader.html", user, body=markdown.render(text),
                title=title_of(text, target.stem), contents=contents, libraries=libraries)


class SecurityHeaders:
    """Adds the Content-Security-Policy to every HTTP response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def with_csp(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append((b"content-security-policy", CSP.encode()))
            await send(message)

        await self.app(scope, receive, with_csp)


def create_app(root: Path) -> Starlette:
    """The web app for one collection, which must be rendered in `vscode`.

    The reader relies on that flavor's relative links and HTML anchors. An
    `obsidian` render links with `[[…]]`, which a browser cannot follow.
    """
    if paths.flavor(root) != "vscode":
        raise SystemExit(
            "%s is rendered in %s. The server reads the vscode flavor: run "
            "`litdb render --flavor vscode` first." % (root, paths.flavor(root))
        )
    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        app.state.worker = state.Worker(root)
        app.state.worker.start()
        yield

    app = Starlette(routes=[
        Route("/", papers),
        Route("/login", login, methods=["GET", "POST"]),
        Route("/logout", logout),
        Route("/add", add, methods=["GET", "POST"]),
        Route("/libraries", library_list),
        Route("/libraries", create_library, methods=["POST"]),
        Route("/libraries/delete", delete_library, methods=["POST"]),
        Route("/libraries/{action:str}", list_in_library, methods=["POST"]),
        Route("/papers/remove", remove_paper, methods=["POST"]),
        Route("/jobs", jobs),
        Route("/jobs/{id:int}/retry", retry, methods=["POST"]),
        Route("/lit/{path:path}", reader),
        Mount("/static", StaticFiles(directory=HERE / "static"), name="static"),
    ], middleware=[Middleware(SecurityHeaders)], lifespan=lifespan)
    app.state.root = root
    app.state.worker = None  # until the lifespan starts it; tests run without one
    return app
