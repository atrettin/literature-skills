#!/usr/bin/env bash
#
# Install the literature skills: the `litdb` command, the six skills and the
# five agents.
#
#     ./install.sh
#
# The skills and the agents are symlinked rather than copied, so a `git pull`
# here updates what Claude Code loads. `litdb` is installed in editable mode for
# the same reason.

set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python="${PYTHON:-python3}"

skills=(add-paper find-papers follow-citations init-literature research-report use-literature)
agents=(paper-ingestor paper-scout terminology-prospector terminology-scout)

echo "installing literature-skills from $repo"

# --- the command ----------------------------------------------------------
echo "  the litdb command, with $($python --version)"
"$python" -m pip install --quiet --disable-pip-version-check --editable "$repo[rerank]"

# --- the skills and the agents --------------------------------------------
mkdir -p ~/.claude/skills ~/.claude/agents

for skill in "${skills[@]}"; do
    ln -sfn "$repo/$skill" ~/.claude/skills/"$skill"
done
echo "  ${#skills[@]} skills  -> ~/.claude/skills/"

for agent in "${agents[@]}"; do
    ln -sfn "$repo/.claude/agents/$agent.md" ~/.claude/agents/"$agent".md
done
echo "  ${#agents[@]} agents  -> ~/.claude/agents/"

# --- say whether it can be run --------------------------------------------
if command -v litdb >/dev/null 2>&1; then
    echo
    echo "done. litdb is $(command -v litdb)"
else
    # pip put the script somewhere that PATH does not reach. Say where, rather
    # than leaving a command that reports "not found" for no visible reason.
    bindir="$("$python" -c 'import sysconfig; print(sysconfig.get_path("scripts"))')"
    echo
    echo "done, but litdb is not on your PATH. It was installed in:"
    echo "    $bindir"
    echo "Add that directory to PATH, for example in ~/.zshrc:"
    echo "    export PATH=\"$bindir:\$PATH\""
    exit 1
fi

echo
echo "Some figures need two more programs, which pip does not install:"
echo "    ghostscript   (gs)            converts an EPS figure"
echo "    librsvg       (rsvg-convert)  converts an SVG figure"
echo "On macOS: brew install ghostscript librsvg"
