#!/usr/bin/env bash
#
# Import skills you authored in the Claude desktop app into this repo's skills/.
#
# The desktop app keeps user-created skills in its own app-managed store, which
# can't be symlinked. Run this after creating or editing a skill in the app to
# copy the latest version here (and thus into Copilot and the Claude Code CLI).
#
# Only skills with creatorType "user" are imported. Anthropic's bundled skills
# (docx, pdf, xlsx, morning, ...) are skipped. Names in SKIP are also skipped.
#
set -euo pipefail

STORE="$HOME/Library/Application Support/Claude/local-agent-mode-sessions/skills-plugin"
DST="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/skills"

# Skills to leave alone (a repo version is preferred over the desktop one).
SKIP="fix-comments"

[ -d "$STORE" ] || { echo "No desktop skills store at $STORE"; exit 0; }

python3 - "$STORE" "$DST" "$SKIP" <<'PY'
import json, glob, os, shutil, sys

store, dst, skip = sys.argv[1], sys.argv[2], set(filter(None, sys.argv[3].split()))

# Newest source dir per user-created skill, across all session manifests.
newest = {}
for m in glob.glob(os.path.join(store, "*", "*", "manifest.json")):
    try:
        data = json.load(open(m))
    except Exception:
        continue
    for s in data.get("skills", []):
        if s.get("creatorType") != "user":
            continue
        name, updated = s["name"], s.get("updatedAt", "")
        src = os.path.join(os.path.dirname(m), "skills", name)
        if os.path.isdir(src) and (name not in newest or updated > newest[name][0]):
            newest[name] = (updated, src)

for name in sorted(newest):
    if name in skip:
        print(f"skip  {name}")
        continue
    target = os.path.join(dst, name)
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(newest[name][1], target)
    print(f"import {name}")
PY
echo "Done. Review with 'git status', then commit."
