# The literature server

`litdb serve` runs one collection for a group. People use it in the browser:
they search, read papers, add papers from arXiv, keep libraries and export them
as BibTeX, and read reports. Agents use it through MCP, with the same commands
the skills describe, under the same names. The server never serves a paper's
PDF or TeX source.

The local folder stays the first way to work. The server is a second one, and
the skills cover both (see [use-literature](../use-literature/SKILL.md)).

## Running it with Docker

On the host, from a clone of this repository:

```bash
cp .env.example .env        # then set BASE_URL, ROOT_PATH and PUBLISH
docker compose up -d --build
```

- **Data:** the collection, the users, the libraries, the ingest jobs and the
  reports are all kept in the volume `literature` at `/data`. The first start
  creates an empty collection there.
- **Restarts:** the container restarts with the host and after a crash
  (`restart: unless-stopped`).
- **The image:** it holds the code, ghostscript and librsvg for figures, and
  the rerank model. It never holds a paper.

### Settings (`.env`)

| Variable | Meaning |
|---|---|
| `BASE_URL` | The address users reach the server at. Rendered reports link to it. |
| `ROOT_PATH` | The prefix the reverse proxy serves the app under, e.g. `/literature`. Leave it empty when the proxy gives the app a whole host. |
| `PUBLISH` | Where the container's port is published. The default `127.0.0.1:8000` accepts connections from the same machine only, which suits a reverse proxy on the host. |

The reverse proxy strips `ROOT_PATH` before it forwards to the published port:
`/literature/login` arrives as `/login`, and the app writes its links with the
prefix. With nginx:

```nginx
location /literature/ {
    proxy_pass http://127.0.0.1:8000/;
    proxy_read_timeout 360s;
}
```

MCP answers are plain
JSON, never a stream, so the proxy needs no special buffering settings. The
proxy's read timeout must exceed five minutes, the longest an `ingest_status`
call waits.

### Users

The administrator issues every token. A token is printed once and is not stored
in a form that can be read back:

```bash
docker compose exec literature litdb serve add-user alice
docker compose exec literature litdb serve add-user --admin bob
```

A user signs in to the web pages with the token, and gives it to the MCP client
(see below). Each user gets a personal library of the same name. An
administrator may also force a re-ingest that replaces a paper, and may remove
papers from the collection.

### Failed ingests

A failed ingest stays on the **Ingests** page. Anyone can queue it again, and
an administrator can force it. A paper that needs a hand fix is worked on
inside the container, where the whole `litdb` command set runs against the
collection:

```bash
docker compose exec literature litdb add-paper --auto <arxiv-id>
```

The paper is then in the collection, and anyone can put it in a library from
the web pages.

### An existing collection

To start from a collection you already have, copy it in before anyone adds
papers, then restart:

```bash
docker compose cp ./literature literature:/data/
docker compose exec literature litdb render --flavor vscode
docker compose restart
```

The server reads the `vscode` flavor only. That is why the copy is rendered
again.

### Backups and updates

- **Backup:** copy the volume while the server is stopped:

  ```bash
  docker compose stop
  docker run --rm -v literature-skills_literature:/data -v "$PWD":/backup \
    busybox tar czf /backup/literature.tgz -C /data .
  docker compose start
  ```

  The volume name starts with the compose project, which is the name of the
  clone's directory. `docker volume ls` shows it. The archive holds the
  papers, so keep it out of git.
- **Update:** `git pull && docker compose up -d --build`.

## Running it without Docker

```bash
pip install ".[server]"
litdb serve add-user --admin <you>
litdb serve --host 0.0.0.0 --port 8000 --base-url https://example.org/literature
```

The collection must already exist, in the `vscode` flavor. `litdb serve` reads
it from `$LITERATURE_ROOT` or `--literature-root`.

## Connecting an agent

Register the server under the name `literature`: the skills and the scouts
refer to its tools by that name. Keep your token in `LITERATURE_TOKEN`.

- **Claude Code:**

  ```bash
  claude mcp add --scope user --transport http literature <BASE_URL>/mcp \
    --header 'Authorization: Bearer ${LITERATURE_TOKEN}' \
    --header 'X-Literature-Library: ${LITERATURE_LIBRARY:-}'
  ```

- **OpenCode**, in `~/.config/opencode/opencode.json`:

  ```json
  "mcp": {
    "literature": {
      "type": "remote",
      "url": "<BASE_URL>/mcp",
      "oauth": false,
      "headers": {
        "Authorization": "Bearer {env:LITERATURE_TOKEN}",
        "X-Literature-Library": "{env:LITERATURE_LIBRARY}"
      }
    }
  }
  ```

### Choosing the collection per project

`LITERATURE_LIBRARY` names the library a project works in. The client sends it
with every request, so agents in that project use that library without being
told. Set it in whatever starts the agent in the project, for example in a
`.envrc` for direnv:

```bash
export LITERATURE_LIBRARY=thesis
```

| Value | Effect |
|---|---|
| unset or empty | Your personal library. If the project also has a local collection, research-report asks which one to use. |
| a library name | That library, without asking. |
| `local` | The project's local folder. The server refuses every tool call, so agents use `litdb` instead. |

The user can always name a different place in the task, and that choice
applies to that task only.
