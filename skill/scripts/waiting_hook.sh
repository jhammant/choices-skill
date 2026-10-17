#!/bin/bash
# SessionStart: show Jon's unacted picks and notes on this workspace's live choices page, so whichever session
# starts next acts on them, not only the session that asked (15 Oct 2026: Román's pick sat 3 days unsent).
# Silent when nothing is waiting or the session isn't in a workspace with a live page.
case "$PWD/" in
  "$HOME/dev/orbital/"*) ws=orbital ;;
  "$HOME/dev/recos/"*)   ws=recos ;;
  *) exit 0 ;;
esac
timeout 10 python3 "$HOME/.claude/skills/choices/scripts/tailnet.py" waiting "$ws" --server "$ws" --older 60 --hook 2>/dev/null || true
