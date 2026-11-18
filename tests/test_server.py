"""The web server: who gets in, and what the reader will and will not serve."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("starlette")
from starlette.testclient import TestClient  # noqa: E402

from lit import paths, render  # noqa: E402
from lit.server import state, web  # noqa: E402

FIXTURE = Path(__file__).parent / "data" / "collection_fixture"


@pytest.fixture
def served(tmp_path):
    root = tmp_path / "collection"
    shutil.copytree(FIXTURE, root)
    render.render_collection(root, "vscode")
    with state.connect(root) as db:
        token = state.add_user(db, "alice")
    client = TestClient(web.create_app(root))
    return root, client, token


def sign_in(client, token):
    response = client.post("/login", data={"token": token}, follow_redirects=False)
    assert response.status_code == 303
    return response


def test_a_stranger_is_sent_to_sign_in(served):
    _, client, _ = served
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].endswith("/login")
    assert client.post("/login", data={"token": "wrong"}).status_code == 200
    assert client.get("/", follow_redirects=False).status_code == 303


def test_the_token_is_stored_only_as_its_hash(served):
    root, _, token = served
    assert token.encode() not in state.db_path(root).read_bytes()


def test_a_user_sees_every_paper_and_reads_a_chapter(served):
    root, client, token = served
    sign_in(client, token)
    listing = client.get("/").text
    slug = paths.papers_on_disk(root)[0]
    assert "/lit/%s/INDEX.md" % slug in listing

    chapter = next((root / slug / paths.CHAPTERS_DIR).glob("*.md"))
    response = client.get("/lit/%s/chapters/%s" % (slug, chapter.name))
    assert response.status_code == 200
    assert "content-security-policy" in response.headers
    assert "Contents of this paper" in response.text


def test_the_reader_serves_no_state_and_nothing_outside(served):
    root, client, token = served
    sign_in(client, token)
    slug = paths.papers_on_disk(root)[0]
    for path in ("/lit/.server.db", "/lit/%s/paper.json" % slug, "/lit/../secret.md",
                 "/lit/%s/../../outside.md" % slug):
        assert client.get(path).status_code == 404, path


def test_maths_reaches_the_page_as_tex():
    html = web.markdown.render("Inline $x_{F}<y$.\n\n$$\na_b \\tag{1}\n$$\n")
    assert '<span class="math inline">x_{F}&lt;y</span>' in html
    assert '<div class="math block">' in html
