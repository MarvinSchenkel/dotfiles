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

## Notes

- `skills/review-pr` is a machine-local symlink into the music-assistant repo,
  so it's gitignored rather than committed.
- Claude Code plugin skills (superpowers, elixir-phoenix, etc.) are managed by
  the plugin system, not here.
