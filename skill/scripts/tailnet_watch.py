#!/usr/bin/env python3
"""Watch Jon's live tailnet /choices pages for new picks (loom job choices-watch, every 2 minutes on the Mac).

For every live page on every configured server (tailnet.py servers), it diffs the page's saved state against the
last state it saw (~/.config/choices/watch/<server>--<slug>.json) and appends each newly answered question (a new
or changed pick or comment) and each changed section note to <root>/choices/<slug>/picks.jsonl:

  {"group", "pick", "comment", "at", "owner", "ws", "title", "section", "page", "voter", "pick_name"}
  (a section note is a line with "group": "" and "note")

Then it sends ONE counts-only notify line, e.g. "Choices: 3 new picks on orbital". Never the content.

On the Orbital server each pick also updates Jon's to-do list at once (14 Oct 2026): a plain pick closes the
question's item (t-ch-<slug>-<group>) with the pick as evidence; a pick with a comment moves it to In flight with
the comment as its why. It never files tickets and never acts on a pick otherwise. Acting stays with a live Claude session: read picks.jsonl (the
"owner" is the session that added the question), act, then `tailnet.py resolve <slug> <group> --note "..."`.

  tailnet_watch.py               # one pass (what the loom job runs)
  tailnet_watch.py --no-notify   # one pass without the notify line (tests)
  tailnet_watch.py --dry-run     # show the counts; write nothing
"""
from __future__ import annotations

import argparse
import fcntl
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tailnet  # noqa: E402

WATCH = Path.home() / ".config" / "choices" / "watch"
NOTIFY = Path.home() / "dev" / "utilities" / "notify" / "bin" / "notify"


def same(a, b) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def flatten(state: dict, manifest: dict) -> dict:
    """{"g|<voter>|<group>": {"pick", "comment", "section", "at"}, "n|<voter>|<section>": {"note", "at"}}"""
    out = {}
    for voter, b in tailnet.ballots(state, manifest).items():
        for gk, row in b["groups"].items():
            out[f"g|{voter}|{gk}"] = dict(row, at=b["at"])
        for sk, note in b["notes"].items():
            out[f"n|{voter}|{sk}"] = {"note": note, "at": b["at"]}
    return out


def changes(prev: dict, cur: dict, manifest: dict, slug: str, ws: str) -> list:
    lines = []
    owners = {}
    for gk, g in manifest["groups"].items():
        owners.setdefault(g.get("section"), g.get("owner", ""))
    for key, row in cur.items():
        kind, voter, name = key.split("|", 2)
        old = prev.get(key)
        if kind == "g":
            if not tailnet.answered(row):
                continue
            if old and same(old.get("pick"), row.get("pick")) and old.get("comment", "") == row.get("comment", ""):
                continue
            g = manifest["groups"].get(name, {})
            pick = row.get("pick")
            vals = pick if isinstance(pick, list) else ([] if pick in (None, "") else [pick])
            lines.append({"group": name, "pick": pick, "comment": row.get("comment", ""), "at": row.get("at") or now(),
                          "owner": g.get("owner", ""), "ws": g.get("ws") or ws, "title": g.get("title", ""),
                          "section": row.get("section"), "page": slug, "voter": voter,
                          "pick_name": [g.get("names", {}).get(str(v), "") for v in vals]})
        elif row.get("note") and (not old or old.get("note") != row.get("note")):
            lines.append({"group": "", "section": name, "note": row["note"], "pick": None, "comment": "",
                          "at": row.get("at") or now(), "owner": owners.get(name, ""), "ws": ws, "page": slug,
                          "voter": voter})
    return lines


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def append(path: Path, lines: list):
    new = not path.exists()
    with open(path, "a") as fh:
        for ln in lines:
            fh.write(json.dumps(ln, ensure_ascii=False) + "\n")
    if new:
        path.chmod(0o600)


TODO = Path.home() / ".claude" / "skills" / "todo" / "scripts" / "todo.py"


def todo_on_pick(srv: dict, slug: str, lines: list) -> int:
    """Jon, 14 Oct 2026: a pick closes its to-do item straight away (no resolve needed). A pick that comes with a
    comment stays open but moves to In flight with the comment as its why, because Claude has to act on it.
    Orbital only; the item is t-ch-<slug>-<group>, added by `tailnet.py add`."""
    if srv.get("ws") != "orbital" or not TODO.exists():
        return 0
    env = {**__import__("os").environ, "TODO_FROM_CHOICES": "1"}   # don't resolve the question: Claude does that after acting
    n = 0
    for ln in lines:
        if not ln.get("group"):
            continue
        iid = f"t-ch-{slug}-{ln['group']}"[:80]
        names = [x for x in (ln.get("pick_name") or []) if x]
        pick = ln.get("pick")
        shown = ", ".join(names) if names else (", ".join(map(str, pick)) if isinstance(pick, list) else str(pick or ""))
        if ln.get("comment"):
            args = ["set", iid, "section=flight", "owner=Claude", "flag=",
                    "why=Your comment: " + ln["comment"].replace("\n", " ")[:220] + (f" (picked: {shown})" if shown else ""),
                    "--by", "choices-watch"]
        elif pick not in (None, "", []):
            args = ["done", iid, "--evidence", f"Picked on the decisions page: {shown}"[:200], "--by", "choices-watch", "--quiet"]
        else:
            continue
        try:
            py = __import__("shutil").which("python3", path="/opt/homebrew/bin:/usr/local/bin") or sys.executable
            r = subprocess.run([py, str(TODO), *args], capture_output=True, text=True, timeout=60, env=env)
            n += r.returncode == 0
        except Exception as e:   # the watcher must keep logging picks even if the list is unavailable
            print(f"{slug}/{ln['group']}: to-do list not updated ({type(e).__name__})")
    return n


def run(dry=False) -> dict:
    counts = {}
    for name, srv in tailnet.servers().items():
        root = Path(srv["root"]).expanduser()
        for live in sorted((root / "choices").glob("*/live.json")):
            d, slug = live.parent, live.parent.name
            try:
                manifest = json.loads(live.read_text())
                state = json.loads(tailnet.state_file(srv, slug).read_text()) if tailnet.state_file(srv, slug).exists() else {}
            except (OSError, ValueError) as e:
                print(f"{name}/{slug}: skipped ({type(e).__name__})")
                continue
            manifest.setdefault("resolved", {})
            cur = flatten(state, manifest)
            snap = WATCH / f"{name}--{slug}.json"
            prev = json.loads(snap.read_text()) if snap.exists() else {}
            lines = changes(prev, cur, manifest, slug, srv["ws"])
            if not dry:
                if lines:
                    append(d / "picks.jsonl", lines)
                    todo_on_pick(srv, slug, lines)
                tailnet.write_json(snap, cur)
            if lines:
                ws = manifest.get("ws") or srv["ws"]
                counts[ws] = counts.get(ws, 0) + len(lines)
                print(f"{name}/{slug}: {len(lines)} new")
    return counts


def notify_line(counts: dict) -> str:
    parts = [f"{n} new pick{'' if n == 1 else 's'} on {ws}" for ws, n in counts.items() if n]
    return "Choices: " + ", ".join(parts) if parts else ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    WATCH.mkdir(parents=True, exist_ok=True)
    WATCH.chmod(0o700)
    with open(WATCH / ".lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return  # a previous pass is still running
        counts = run(dry=a.dry_run)
    line = notify_line(counts)
    if not line:
        return
    print(line)
    if a.dry_run or a.no_notify or not NOTIFY.exists():
        return
    subprocess.run([str(NOTIFY), line, "--title", "Choices"], check=False)


if __name__ == "__main__":
    main()
