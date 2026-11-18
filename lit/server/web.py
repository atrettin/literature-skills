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


@signed_in
async def papers(request: Request, user: str) -> Response:
    root: Path = request.app.state.root
    rows = []
    for slug in paths.papers_on_disk(root):
        paper = paths.read_paper(root, slug)
        rows.append({
            "slug": slug,
            "title": paper.get("title") or slug,
            "authors": short_authors(paper.get("authors") or []),
            "year": paper.get("year") or "",
        })
    rows.sort(key=lambda row: (-int(row["year"] or 0), row["title"].lower()))
    return page(request, "papers.html", user, papers=rows)


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
    return page(request, "reader.html", user, body=markdown.render(text),
                title=title_of(text, target.stem), contents=contents)


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
    app = Starlette(routes=[
        Route("/", papers),
        Route("/login", login, methods=["GET", "POST"]),
        Route("/logout", logout),
        Route("/lit/{path:path}", reader),
        Mount("/static", StaticFiles(directory=HERE / "static"), name="static"),
    ], middleware=[Middleware(SecurityHeaders)])
    app.state.root = root
    return app
