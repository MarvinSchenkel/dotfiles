#!/usr/bin/env bash
# SessionStart hook: a linked git worktree shares the auto-memory folder of its main checkout.
# Claude Code keys memory on the session cwd, so every worktree would otherwise start with empty memory.
set -u
cwd="$(jq -r '.cwd // empty' 2>/dev/null)"
[ -n "$cwd" ] || cwd="$PWD"
git -C "$cwd" rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0
top="$(git -C "$cwd" rev-parse --show-toplevel)"
main="$(dirname "$(git -C "$cwd" rev-parse --path-format=absolute --git-common-dir)")"
[ "$main" != "$top" ] || exit 0
slug() { printf '%s' "$1" | sed 's#[^A-Za-z0-9-]#-#g'; }
projects="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects"
src="$projects/$(slug "$main")/memory"
dst="$projects/$(slug "$top")/memory"
[ -L "$dst" ] && exit 0
mkdir -p "$src" "$(dirname "$dst")"
if [ -d "$dst" ]; then
  cp -n "$dst"/* "$src"/ 2>/dev/null || true
  rm -rf "$dst"
fi
ln -s "$src" "$dst"
echo "memory: $top -> $main"
