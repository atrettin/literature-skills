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


def test_a_library_lists_papers_without_copying_them(served):
    root, client, token = served
    sign_in(client, token)
    slug = paths.papers_on_disk(root)[0]
    assert client.post("/libraries", data={"name": "thesis"}).status_code == 200
    client.post("/libraries/add", data={"library": "thesis", "slug": slug})
    page = client.get("/?library=thesis").text
    assert "/lit/%s/INDEX.md" % slug in page and "1 papers." in page
    client.post("/libraries/remove", data={"library": "thesis", "slug": slug})
    assert "0 papers." in client.get("/?library=thesis").text
    assert paths.paper_path(root, slug).is_file()
    assert client.post("/libraries/add", data={"library": "thesis", "slug": "nope"}).status_code == 404


def test_a_held_paper_is_listed_and_a_new_one_queued_once(served):
    root, _, _ = served
    slug = paths.papers_on_disk(root)[0]
    held = paths.read_paper(root, slug)["arxiv_id"]
    with state.connect(root) as db:
        assert state.add_paper(db, root, "arXiv:%sv2" % held, "alice", "alice") == ("listed", slug)
        assert state.library_slugs(db, "alice") == [slug]
        outcome, job_id = state.add_paper(db, root, "2401.00001", "alice", "alice")
        assert outcome == "queued"
        assert job(db, job_id)["source"] == "arxiv:2401.00001"
        with pytest.raises(ValueError):
            state.add_paper(db, root, "not-an-id", "alice", "alice")


def job(db, job_id) -> dict:
    found = state.job(db, int(job_id))
    assert found is not None
    return found


def fake_ingest(code: int, report: dict):
    """An add-paper that prints `report` and exits with `code`, without arXiv."""
    import json
    import sys
    script = "import json,sys; print(json.dumps(%r)); sys.exit(%d)" % (report, code)
    return lambda root, source, force: [sys.executable, "-c", script]


def test_the_worker_lists_what_it_ingested_and_keeps_what_failed(served, monkeypatch):
    root, _, _ = served
    slug = paths.papers_on_disk(root)[0]
    with state.connect(root) as db:
        _, ok_id = state.add_paper(db, root, "2401.00001", "alice", "alice")
        _, bad_id = state.add_paper(db, root, "2401.00002", "alice", "alice")

        monkeypatch.setattr(state, "ingest_command", fake_ingest(0, {"status": "ingested", "slug": slug}))
        state.run_job(db, root, db.execute("SELECT * FROM jobs WHERE id = ?", (ok_id,)).fetchone())
        exception = {"status": "exception", "exception": {"code": "NO_ARXIV_SOURCE", "detail": "PDF only"}}
        monkeypatch.setattr(state, "ingest_command", fake_ingest(2, exception))
        state.run_job(db, root, db.execute("SELECT * FROM jobs WHERE id = ?", (bad_id,)).fetchone())

        assert job(db, ok_id)["status"] == "done"
        assert state.library_slugs(db, "alice") == [slug]
        failed = job(db, bad_id)
        assert failed["status"] == "failed"
        assert failed["report"]["exception"]["code"] == "NO_ARXIV_SOURCE"

        state.retry(db, int(bad_id), force=True)
        assert job(db, bad_id)["status"] == "queued"
        db.execute("UPDATE jobs SET status = 'running' WHERE id = ?", (bad_id,))
        state.requeue_interrupted(db)
        assert job(db, bad_id)["status"] == "queued"


def test_only_an_admin_forces_a_retry(served):
    root, client, token = served
    sign_in(client, token)
    with state.connect(root) as db:
        _, job_id = state.add_paper(db, root, "2401.00002", "alice", "alice")
        db.execute("UPDATE jobs SET status = 'failed' WHERE id = ?", (job_id,))
        db.commit()
    client.post("/jobs/%s/retry" % job_id, data={"force": "1"})
    with state.connect(root) as db:
        assert job(db, job_id)["force"] == 0
