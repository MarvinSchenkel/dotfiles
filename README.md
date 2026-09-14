# dotfiles

Shared AI config for Claude Code (desktop) and the GitHub Copilot CLI. Both
tools read the same skills and the same global instructions through symlinks, so
there's one place to edit and nothing drifts out of sync.

## Layout

```
skills/                    skill dirs (each is <name>/SKILL.md + assets)
copilot-instructions.md    global engineering + behaviour + PR-workflow instructions
install.sh                 recreates the symlinks on a new machine
```

## Symlinks

`install.sh` wires these up:

| Link | Target |
|------|--------|
| `~/.claude/skills` | `skills/` |
| `~/.copilot/skills` | `skills/` |
| `~/.copilot/copilot-instructions.md` | `copilot-instructions.md` |
| `~/.claude/CLAUDE.md` | `copilot-instructions.md` |

Both tools use the same skill format (a directory per skill holding `SKILL.md`
with `name` + `description` frontmatter), so one shared `skills/` dir serves
both.

## Setup on a new machine

```bash
git clone git@github.com:MarvinSchenkel/dotfiles.git ~/git/dotfiles
~/git/dotfiles/install.sh
```

## Desktop app skills

Skills authored in the Claude desktop app UI live in that app's own store
(`~/Library/Application Support/Claude/local-agent-mode-sessions/...`), keyed by
session and skill IDs. That store can't be symlinked, so those skills are
**copied** into `skills/` here rather than linked. After creating or editing one
in the app, re-sync with:

```bash
~/git/dotfiles/import-desktop-skills.sh
```

It imports only skills you created (`creatorType: user`), skips Anthropic's
bundled ones, and skips anything listed in `SKIP` at the top of the script
(currently `fix-comments`, since the repo's `fix_comments` is preferred).

## Notes

- `skills/review-pr` is a machine-local symlink into the music-assistant repo,
  so it's gitignored rather than committed.
- Claude Code plugin skills (superpowers, elixir-phoenix, etc.) are managed by
  the plugin system, not here.
