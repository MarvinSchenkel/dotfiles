#!/usr/bin/env bash
#
# Symlink Claude Code and GitHub Copilot CLI at this repo's shared config.
# Idempotent: re-running is safe. Existing non-symlink targets are backed up.
#
set -euo pipefail

DOTFILES="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

link() {
  local src="$1" dest="$2"
  mkdir -p "$(dirname "$dest")"
  if [ -L "$dest" ] && [ "$(readlink "$dest")" = "$src" ]; then
    echo "ok    $dest"
    return
  fi
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    mv "$dest" "$dest.bak.$(date +%s)"
    echo "backup $dest -> $dest.bak.*"
  fi
  ln -s "$src" "$dest"
  echo "link  $dest -> $src"
}

link "$DOTFILES/skills"                  "$HOME/.claude/skills"
link "$DOTFILES/skills"                  "$HOME/.copilot/skills"
link "$DOTFILES/copilot-instructions.md" "$HOME/.copilot/copilot-instructions.md"
link "$DOTFILES/copilot-instructions.md" "$HOME/.claude/CLAUDE.md"

# Second Claude config dir (team seat used for routines); shares everything but plugins and settings.
TEAMB="$HOME/.claude-teamB"
if [ -d "$TEAMB" ]; then
  link "$DOTFILES/skills"                  "$TEAMB/skills"
  link "$DOTFILES/copilot-instructions.md" "$TEAMB/CLAUDE.md"
  link "$HOME/.claude/output-styles"       "$TEAMB/output-styles"
  link "$HOME/.claude/projects"            "$TEAMB/projects"
fi

echo "Done."
