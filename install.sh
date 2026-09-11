#!/usr/bin/env bash
#
# Install the literature skills: the `litdb` command, the six skills, and the
# three agents — for Claude Code, for OpenCode, or for both.
#
#     ./install.sh --for claude
#     ./install.sh --for opencode [--small MODEL] [--large MODEL]
#     ./install.sh --for both
#
# The skills are symlinked, so a `git pull` here updates what the backend
# loads. The agents are generated: each carries a small header that differs
# between the two backends, so the install writes the copy the backend reads
# rather than symlinking the source. Re-run the install after editing an agent
# in agents/. `litdb` is installed in editable mode, for the same reason as
# the skills.

set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python="${PYTHON:-python3}"

skills=(add-paper find-papers find-terms follow-citations research-report use-literature)
agents=(paper-ingestor paper-scout terminology-prospector)

for_backend=""
small_model=""
large_model=""

usage() {
    echo "usage: $0 --for <claude|opencode|both> [--small MODEL] [--large MODEL]" >&2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --for)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            for_backend="$2"; shift 2 ;;
        --small)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            small_model="$2"; shift 2 ;;
        --large)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            large_model="$2"; shift 2 ;;
        -h|--help)
            usage; exit 0 ;;
        *)
            echo "unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

if [[ -z "$for_backend" ]]; then
    echo "error: --for is required" >&2
    usage
    exit 2
fi

backends=()
case "$for_backend" in
    claude)   backends=(claude) ;;
    opencode) backends=(opencode) ;;
    both)     backends=(claude opencode) ;;
    *)
        echo "error: --for must be claude, opencode, or both (got: $for_backend)" >&2
        usage; exit 2 ;;
esac

echo "installing literature-skills from $repo, for: ${backends[*]}"

# --- the command ----------------------------------------------------------
echo "  the litdb command, with $($python --version)"
"$python" -m pip install --quiet --disable-pip-version-check --editable "$repo[rerank]"

# --- reading an agent's source --------------------------------------------
# The line of the closing frontmatter fence: the second line that is exactly
# `---`. The body is everything after it.
closing_fence() {
    awk '/^---$/{c++; if (c == 2) {print NR; exit}}' "$1"
}

# The value of a frontmatter field: the text after `key:` up to the fence.
# (Not `close` as the awk variable: that is the name of awk's built-in
# close() function, and BSD awk will not let you shadow it.)
fm_field() {  # $1=file  $2=key
    local fence
    fence="$(closing_fence "$1")"
    awk -v key="$2" -v fence="$fence" '
        NR < fence && index($0, key ":") == 1 {
            sub(/^[^:]*:[ \t]*/, ""); print; exit
        }
    ' "$1"
}

# The body: every line after the closing fence.
fm_body() {  # $1=file
    local close
    close="$(closing_fence "$1")"
    tail -n +"$((close + 1))" "$1"
}

# The model a backend assigns a tier. Empty means "write no model line": for
# Claude that never happens (it falls back to haiku/sonnet), for OpenCode it
# means the subagent inherits the model of the agent that invoked it.
resolve_model() {  # $1=backend  $2=tier
    case "$1" in
        claude)
            case "$2" in
                small) echo "${small_model:-haiku}" ;;
                large) echo "${large_model:-sonnet}" ;;
            esac ;;
        opencode)
            case "$2" in
                small) echo "$small_model" ;;
                large) echo "$large_model" ;;
            esac ;;
    esac
}

# --- writing one backend --------------------------------------------------
install_skills() {  # $1=skills dir
    local dest="$1" skill
    for skill in "${skills[@]}"; do
        ln -sfn "$repo/$skill" "$dest/$skill"
    done
}

install_agents() {  # $1=backend  $2=agents dir
    local backend="$1" dest="$2" agent src name tier tools desc edit bash_perm model
    for agent in "${agents[@]}"; do
        src="$repo/agents/$agent.md"
        if [[ ! -f "$src" ]]; then
            echo "error: no source for agent '$agent' at $src" >&2; exit 1
        fi
        name="$agent"
        tier="$(fm_field "$src" model-tier)"
        case "$tier" in
            small|large) ;;
            *) echo "error: $src has model-tier '$tier' (want small or large)" >&2; exit 1 ;;
        esac
        model="$(resolve_model "$backend" "$tier")"
        desc="$(fm_field "$src" description)"

        # Replace a stale install — including a dangling symlink an older
        # install left behind — with a fresh regular file, so the write never
        # follows a link out of the backend's directory.
        rm -f "$dest/$name.md"
        {
            if [[ "$backend" == claude ]]; then
                tools="$(fm_field "$src" tools)"
                echo "---"
                echo "name: $name"
                echo "description: $desc"
                echo "tools: $tools"
                if [[ -n "$model" ]]; then echo "model: $model"; fi
                echo "---"
            else
                edit="$(fm_field "$src" edit)"
                bash_perm="$(fm_field "$src" bash)"
                echo "---"
                echo "description: $desc"
                echo "mode: subagent"
                echo "permission:"
                echo "  edit: $edit"
                echo "  bash: $bash_perm"
                if [[ -n "$model" ]]; then echo "model: $model"; fi
                echo "---"
            fi
            fm_body "$src"
        } > "$dest/$name.md"
    done
}

# --- the skills and the agents, per backend --------------------------------
for backend in "${backends[@]}"; do
    case "$backend" in
        claude)   base="$HOME/.claude" ;;
        opencode) base="$HOME/.config/opencode" ;;
    esac
    mkdir -p "$base/skills" "$base/agents"
    install_skills "$base/skills"
    install_agents "$backend" "$base/agents"
    echo "  ${#skills[@]} skills, ${#agents[@]} agents  -> $base/"
done

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
