"""`litdb serve`: the shared collection, as web pages for people and MCP for agents.

    litdb serve [--host H] [--port P] [--root-path /prefix]   run the server
    litdb serve add-user [--admin] <name>                     print a new user's token

The server needs the `server` extra: `pip install ".[server]"`.
"""

from __future__ import annotations

import os
import sqlite3
import sys

from lit import cli


def build_parser():
    parser = cli.parser(__doc__)
    cli.add_root_argument(parser)
    sub = parser.add_subparsers(dest="action")
    add = sub.add_parser("add-user", help="create a user and print their token once")
    add.add_argument("name")
    add.add_argument("--admin", action="store_true",
                     help="may force a re-ingest that replaces a paper the collection holds")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument(
        "--root-path",
        default=os.environ.get("ROOT_PATH", ""),
        help="the prefix a reverse proxy serves the app under, e.g. /spark/literature",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = cli.parse(build_parser(), argv)
    root = args.literature_root
    if not root.is_dir():
        print("lit: no collection at %s. Start one with `litdb init`." % root, file=sys.stderr)
        return cli.ABSENT

    if args.action == "add-user":
        from lit.server import state

        with state.connect(root) as db:
            try:
                token = state.add_user(db, args.name, args.admin)
            except (ValueError, sqlite3.IntegrityError) as error:
                print("lit: %s" % error, file=sys.stderr)
                return cli.JUDGEMENT
        print(token)
        return 0

    import uvicorn

    from lit.server.web import create_app

    uvicorn.run(create_app(root), host=args.host, port=args.port, root_path=args.root_path,
                proxy_headers=True)
    return 0
