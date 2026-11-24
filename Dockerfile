# `litdb serve` for a group: the collection as web pages and an MCP endpoint.
# docs/server.md says how to run it.
FROM python:3.12-slim

# Figure conversion during an ingest: gs for EPS/PS/PDF, rsvg-convert for SVG.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ghostscript librsvg2-bin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY lit lit
# The rerank model goes into the image, so a fresh container ranks from its first search.
RUN pip install --no-cache-dir ".[server,rerank]" \
    && python -c "import sys; from lit import rerank; sys.exit(rerank.download_model())"

ENV LITERATURE_ROOT=/data/literature HOST=0.0.0.0 PORT=8000
VOLUME /data
EXPOSE 8000

# `init` creates the collection on the first start, in the flavor the server
# reads; on every later start it refuses, as the collection exists.
CMD ["sh", "-c", "litdb init --flavor vscode > /dev/null; exec litdb serve"]
