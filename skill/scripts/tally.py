#!/usr/bin/env python3
"""Tally /choices votes into a markdown summary.

Usage:
  tally.py <votes_dir> choices.json [more.json ...]

<votes_dir> is the ArtifactData out_dir from a `list` of the `votes` collection (one JSON file per voter, in the
<out_dir>/votes/ subfolder or directly in it). Voter ids are printed as-is: resolve them to names with
ArtifactData `profiles` and substitute them when writing the decision record.
"""
import json
import sys
from pathlib import Path


def load_votes(folder):
    folder = Path(folder)
    files = list((folder / "votes").glob("*.json")) or list(folder.glob("*.json"))
    votes = {}
    for f in files:
        doc = json.loads(f.read_text())
        data = doc.get("data", doc) if isinstance(doc, dict) else {}
        vid = doc.get("id", f.stem) if isinstance(doc, dict) else f.stem
        if vid == "probe":
            continue
        votes[vid] = data.get("sections", {})
    return votes


def as_list(v):
    return v if isinstance(v, list) else ([v] if isinstance(v, str) and v else [])


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    votes = load_votes(sys.argv[1])
    sections = []
    for p in sys.argv[2:]:
        sections += json.loads(Path(p).read_text()).get("sections", [])
    print(f"Voters: {len(votes)} ({', '.join(votes) or 'none'})\n")
    for s in sections:
        print(f"## {s['title']}\n")
        for g in s["groups"]:
            mode = g.get("mode", "one")
            names = {str(o["value"]): o.get("name", o["value"]) for o in g["options"]}
            score = {v: 0 for v in names}
            per_voter = []
            for vid, secs in votes.items():
                picks = as_list(((secs.get(s["key"]) or {}).get("picks") or {}).get(g["key"]))
                if not picks:
                    continue
                per_voter.append(f"{vid}: {' > '.join(picks) if mode == 'rank' else ', '.join(picks)}")
                for i, v in enumerate(picks):
                    score[v] = score.get(v, 0) + ((len(picks) - i) if mode == "rank" else 1)
            ranked = sorted(score.items(), key=lambda kv: -kv[1])
            unit = "pts" if mode == "rank" else "votes"
            top = ranked[0][1] if ranked else 0
            winners = [v for v, n in ranked if n == top and n > 0]
            verdict = ("**Tie:** " if len(winners) > 1 else "**Winner:** ") + ", ".join(f"{v} {names.get(v, '')}" for v in winners) if winners else "_No votes yet_"
            print(f"### {g['title']} ({mode})\n{verdict}\n")
            for v, n in ranked:
                label = unit if mode == "rank" else ("vote" if n == 1 else "votes")
                print(f"- {v} {names.get(v, '')}: {n} {label}")
            if per_voter:
                print("\n" + "\n".join(f"  - {line}" for line in per_voter))
            print()
        notes = [(vid, (secs.get(s["key"]) or {}).get("note", "")) for vid, secs in votes.items()]
        notes = [(vid, n) for vid, n in notes if n]
        if notes:
            print("Notes:")
            for vid, n in notes:
                print(f"- {vid}: {n}")
            print()


if __name__ == "__main__":
    main()
