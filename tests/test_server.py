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


def test_only_the_owner_deletes_a_library_and_the_papers_stay(served):
    root, client, token = served
    slug = paths.papers_on_disk(root)[0]
    with state.connect(root) as db:
        bob = state.add_user(db, "bob")
        state.create_library(db, "thesis", "alice")
        state.add_to_library(db, "thesis", slug, "alice")
    sign_in(client, bob)
    assert "thesis" in client.get("/libraries").text
    assert client.post("/libraries/delete", data={"name": "thesis"}).status_code == 403
    sign_in(client, token)
    assert client.post("/libraries/delete", data={"name": "alice"}).status_code == 403
    assert client.post("/libraries/delete", data={"name": "thesis"}).status_code == 200
    with state.connect(root) as db:
        assert not state.library_exists(db, "thesis")
        assert db.execute("SELECT COUNT(*) FROM library_papers").fetchone()[0] == 0
    assert paths.paper_path(root, slug).is_file()


def test_only_an_admin_removes_a_paper_and_it_leaves_every_library(served):
    root, client, token = served
    slug = paths.papers_on_disk(root)[0]
    with state.connect(root) as db:
        admin = state.add_user(db, "root", admin=True)
        state.add_to_library(db, "alice", slug, "alice")
    sign_in(client, token)
    assert client.post("/papers/remove", data={"slug": slug}).status_code == 403
    assert paths.paper_path(root, slug).is_file()

    sign_in(client, admin)
    assert "/papers/remove" in client.get("/").text
    state.WRITE_LOCK.acquire()
    try:
        assert client.post("/papers/remove", data={"slug": slug}).status_code == 409
    finally:
        state.WRITE_LOCK.release()
    assert client.post("/papers/remove", data={"slug": slug, "force": "1"}).status_code == 200
    assert not (root / slug).exists()
    with state.connect(root) as db:
        assert state.library_slugs(db, "alice") == []


def test_search_covers_the_library_or_the_whole_collection(served):
    root, client, token = served
    sign_in(client, token)
    first, second = paths.papers_on_disk(root)[:2]
    with state.connect(root) as db:
        state.add_to_library(db, "alice", first, "alice")

    page = client.get("/search", params={"q": "the", "in": "library", "library": "alice"}).text
    assert "/lit/%s/chapters/" % first in page and "/lit/%s/" % second not in page
    assert "in 1 paper searched" in page
    page = client.get("/search", params={"q": "the", "in": "collection"}).text
    assert "in 2 papers searched" in page

    with state.connect(root) as db:
        state.create_library(db, "empty", "alice")
    page = client.get("/search", params={"q": "the", "library": "empty"}).text
    assert "lists no papers yet" in page and "/chapters/" not in page
    page = client.get("/search", params={"q": "the", "in": "collection", "mode": "approx"}).text
    assert "Search a library instead" in page


def test_a_library_exports_as_bibtex(served):
    root, client, token = served
    sign_in(client, token)
    slug = paths.papers_on_disk(root)[0]
    with state.connect(root) as db:
        state.add_to_library(db, "alice", slug, "alice")
    response = client.get("/libraries/alice/bibtex")
    assert response.headers["content-disposition"] == 'attachment; filename="alice.bib"'
    assert response.text.startswith("@") and "{%s," % slug in response.text


def test_a_journal_reference_splits_into_its_fields():
    entry = web.bibtex_entry("k", {"authors": ["A", "B"], "title": "R&D", "arxiv_id": "1",
                                   "publication": {"journal": "Rev.Mod.Phys. 84 (2012) 1307-1341"}})
    assert "journal = {Rev.Mod.Phys.}" in entry and "pages = {1307--1341}" in entry
    assert "title = {{R\\&D}}" in entry and entry.startswith("@article{k,")


def mcp_call(client, token, name, arguments, library=None):
    import json
    headers = {"Authorization": "Bearer %s" % token, "Accept": "application/json, text/event-stream"}
    if library is not None:
        headers["X-Literature-Library"] = library
    response = client.post("/mcp", headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
              "params": {"name": name, "arguments": arguments}})
    result = response.json()["result"]
    text = result["content"][0]["text"]
    return result.get("isError", False), (text if result.get("isError") else json.loads(text))


def test_mcp_needs_a_token_and_reads_the_callers_library(tmp_path):
    root = tmp_path / "collection"
    shutil.copytree(FIXTURE, root)
    render.render_collection(root, "vscode")
    first = paths.papers_on_disk(root)[0]
    with state.connect(root) as db:
        token = state.add_user(db, "alice")
        state.add_to_library(db, "alice", first, "alice")
        state.create_library(db, "empty", "alice")
    with TestClient(web.create_app(root, "https://example.org/lit-server")) as client:
        assert client.post("/mcp", json={}).status_code == 401

        _, listed = mcp_call(client, token, "papers", {})
        assert [p["slug"] for p in listed["papers"]] == [first]
        _, found = mcp_call(client, token, "search", {"phrase": "the", "max_results": 1})
        assert found["exit"] == 0 and found["scope"]["papers"] == [first]

        failed, why = mcp_call(client, token, "search", {"phrase": "the", "library": "empty"})
        assert failed and "lists no papers yet" in why



def test_an_agent_keeps_its_report_and_log_on_the_server(tmp_path):
    root = tmp_path / "collection"
    shutil.copytree(FIXTURE, root)
    render.render_collection(root, "vscode")
    first = paths.papers_on_disk(root)[0]
    with state.connect(root) as db:
        token = state.add_user(db, "alice")
    with TestClient(web.create_app(root, "https://example.org/lit-server")) as client:
        mcp_call(client, token, "append_log", {"name": "q", "entry": "searched one"})
        _, logged = mcp_call(client, token, "append_log", {"name": "q", "entry": "read two"})
        assert logged["words"] == 4
        _, read = mcp_call(client, token, "read_report", {"name": "q", "part": "log"})
        assert read["text"] == "searched one\n\nread two\n"

        text = "# Q\n\nA claim ([§](lit:%s)). Another ([§](lit:nobody_1999_x)).\n" % first
        _, written = mcp_call(client, token, "write_report", {"name": "q", "text": text})
        assert "text" not in written
        failed, why = mcp_call(client, token, "edit_report",
                               {"name": "q", "old_text": "absent", "new_text": "x"})
        assert failed and "does not contain" in why
        failed, why = mcp_call(client, token, "edit_report",
                               {"name": "q", "old_text": "([§]", "new_text": "x"})
        assert failed and "2 times" in why

        _, checked = mcp_call(client, token, "check_report", {"name": "q"})
        assert not checked["ok"] and checked["research_log"] and "report" not in checked
        assert [m["marker"] for m in checked["broken_markers"]] == ["lit:nobody_1999_x"]

        mcp_call(client, token, "edit_report", {"name": "q", "old_text": " Another ([§](lit:nobody_1999_x)).",
                                                "new_text": ""})
        _, rendered = mcp_call(client, token, "render_report", {"name": "q"})
        assert rendered == {"url": "https://example.org/lit-server/reports/alice/q",
                            "log": "https://example.org/lit-server/reports/alice/q?part=log",
                            "download": "https://example.org/lit-server/reports/alice/q.md",
                            "unresolved": []}

        sign_in(client, token)
        download = client.get("/reports/alice/q.md").text
        assert "(https://example.org/lit-server/lit/%s/INDEX.md)" % first in download


def test_a_report_is_private_until_its_owner_shares_it(served):
    root, client, token = served
    with state.connect(root) as db:
        bob = state.add_user(db, "bob")
        state.write_report(db, "alice", "q", "text", "# Q\n\n<script>alert(1)</script>\n")
    sign_in(client, bob)
    assert client.get("/reports/alice/q").status_code == 404
    assert "alice" not in client.get("/reports").text.split("<main>")[1]
    assert client.post("/reports/visibility",
                       data={"owner": "alice", "name": "q", "public": "1"}).status_code == 403
    assert client.post("/reports/delete", data={"owner": "alice", "name": "q"}).status_code == 403

    sign_in(client, token)
    client.post("/reports/visibility", data={"owner": "alice", "name": "q", "public": "1"})
    sign_in(client, bob)
    shown = client.get("/reports/alice/q").text
    assert "&lt;script&gt;" in shown and "<script>alert" not in shown

    sign_in(client, token)
    client.post("/reports/delete", data={"owner": "alice", "name": "q"})
    assert client.get("/reports/alice/q").status_code == 404


# The tool each command is, and the module whose parser defines the command.
WRAPPED = {"search": "search_literature", "show": "show_text", "toc": "toc",
           "lookup": "reference_lookup", "citations": "inspire_citations", "find": "arxiv_discover",
           "overlap": "collection_overlap", "terminology": "terminology_scan"}


def test_every_tool_parameter_is_an_option_of_its_command(served):
    """`litdb X --some-opt v` is the tool `X(some_opt=v)`: the skills rely on it."""
    import importlib
    _, client, token = served
    with client:  # the MCP session manager runs in the lifespan
        listed = client.post("/mcp", headers={
            "Authorization": "Bearer %s" % token, "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]
    params = {tool["name"]: set(tool["inputSchema"]["properties"]) for tool in listed}
    for tool, module in WRAPPED.items():
        parser = importlib.import_module("lit." + module).build_parser()
        names = {action.dest for action in parser._actions if not action.option_strings}
        names |= {option[2:].replace("-", "_") for action in parser._actions
                  for option in action.option_strings if option.startswith("--")}
        assert params[tool] - {"library"} <= names, (tool, params[tool] - {"library"} - names)


def test_the_project_chooses_the_default_library(tmp_path):
    root = tmp_path / "collection"
    shutil.copytree(FIXTURE, root)
    render.render_collection(root, "vscode")
    first, second = paths.papers_on_disk(root)[:2]
    with state.connect(root) as db:
        token = state.add_user(db, "alice")
        state.add_to_library(db, "alice", first, "alice")
        state.create_library(db, "thesis", "alice")
        state.add_to_library(db, "thesis", second, "alice")
        with pytest.raises(ValueError):
            state.create_library(db, "local", "alice")
    with TestClient(web.create_app(root)) as client:
        _, listed = mcp_call(client, token, "papers", {}, library="thesis")
        assert [p["slug"] for p in listed["papers"]] == [second]
        _, found = mcp_call(client, token, "search", {"phrase": "the", "max_results": 1},
                            library="thesis")
        assert found["scope"]["papers"] == [second]
        _, chosen = mcp_call(client, token, "libraries", {}, library="thesis")
        assert (chosen["default_library"], chosen["chosen_by"]) == ("thesis", "project")

        _, listed = mcp_call(client, token, "papers", {}, library="")
        assert [p["slug"] for p in listed["papers"]] == [first]

        failed, why = mcp_call(client, token, "papers", {}, library="nowhere")
        assert failed and "LITERATURE_LIBRARY" in why
        failed, why = mcp_call(client, token, "papers", {}, library="local")
        assert failed and "local collection" in why

        _, terms = mcp_call(client, token, "terminology", {"topic": "neural network"})
        assert terms["exit"] in (0, 1) and "error" not in terms
        failed, why = mcp_call(client, token, "overlap", {"arxiv_id": "1706.03762"},
                               library="empty-and-absent")
        assert failed and "no library named" in why


def test_ingest_status_waits_for_the_job(served, monkeypatch):
    root, client, token = served
    slug = paths.papers_on_disk(root)[0]
    monkeypatch.setattr(state, "ingest_command", fake_ingest(0, {"status": "ingested", "slug": slug}))
    with client:  # the lifespan starts the worker
        _, added = mcp_call(client, token, "add", {"arxiv_ids": ["2401.00003"]})
        queued = added["results"][0]["job"]
        _, status = mcp_call(client, token, "ingest_status", {"job": queued, "wait": 30})
        assert status["jobs"][0]["status"] == "done"
