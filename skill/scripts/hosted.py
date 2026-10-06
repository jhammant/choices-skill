#!/usr/bin/env python3
"""Hosted /choices pages on choices.hammantlabs.com (for voters outside claude.ai).

  hosted.py build choices.json [more.json ...] --slug pricing [--open] [--owner Jon]   # bundle + owner link
  hlsite deploy ~/hammantlabs-sites-work/choices/<slug>                                # publish it
  hosted.py invite <slug> "Anna" "Ben Smith" ...    # one personal voting link each
  hosted.py status <slug>                           # who has opened, who has voted
  hosted.py votes <slug> <out_dir>                  # export for tally.py (files named by voter)
  hosted.py close <slug> | reopen <slug>

The page is the normal choices picker plus a small shim that talks to the page's own server instead of claude.ai.
Invite-only by default: only personal links can vote; anyone else with the URL sees results only. --open lets
anyone with the URL vote after typing a name. Jon gets a Discord alert when someone opens it, votes, changes a vote
(at most every 30 min each) and when everyone invited has voted.

Secrets stay local: the owner token and voter links live in ~/.config/choices/hosted/<slug>.json (0600). The
deployed bundle only holds the owner token's SHA-256.
"""
import argparse
import hashlib
import json
import secrets
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets" / "hosted"
WORK = Path.home() / "hammantlabs-sites-work" / "choices"
STORE = Path.home() / ".config" / "choices" / "hosted"
HOST = "https://choices.hammantlabs.com"
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"

sys.path.insert(0, str(HERE))
import build_choices  # noqa: E402


def fail(msg):
    sys.exit(f"hosted: {msg}")


def record(slug: str) -> dict:
    f = STORE / f"{slug}.json"
    if not f.exists():
        fail(f"no local record for {slug} in {STORE}")
    return json.loads(f.read_text())


def save_record(slug: str, rec: dict) -> None:
    STORE.mkdir(parents=True, exist_ok=True)
    STORE.chmod(0o700)
    f = STORE / f"{slug}.json"
    f.write_text(json.dumps(rec, indent=2) + "\n")
    f.chmod(0o600)


def call(rec: dict, method: str, path: str, body=None):
    req = urllib.request.Request(rec["url"] + "api/" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json", "x-hl-token": rec["owner_token"],
                                          "user-agent": "choices-hosted"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        fail(f"{method} {path}: {e.code} {e.read().decode('utf-8', 'replace')[:200]}")


def cmd_build(a):
    base = a.slug.lower().strip("-")
    slug = base if a.exact_slug else f"{base}-{''.join(secrets.choice(ALPHABET) for _ in range(8))}"
    out = WORK / slug
    if out.exists():
        fail(f"{out} exists")
    (out / "public").mkdir(parents=True)
    page = out / "public" / "index.html"
    head, meta = build_choices.build(a.inputs, page)
    owner = a.owner or head.get("owner") or "Jon"
    url = f"{HOST}/{slug}/"

    hosted_meta = dict(meta, hosted=True, open=bool(a.open), owner=owner, invite="")
    html = page.read_text()
    old = json.dumps(meta, ensure_ascii=False).replace("</", "<\\/")
    if html.count(old) != 1:
        fail("couldn't find the page META to mark it hosted")
    html = html.replace(old, json.dumps(hosted_meta, ensure_ascii=False).replace("</", "<\\/"))
    boot = (f'<meta name="robots" content="noindex">\n<script>window.CHOICES_HOSTED = '
            f'{json.dumps({"open": bool(a.open), "owner": owner})};</script>\n'
            f'<script>\n{(ASSETS / "shim.js").read_text()}</script>\n')
    # The template is a fragment (claude.ai wraps artifacts in a document); give the hosted page a real one.
    doc = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
           '<meta name="viewport" content="width=device-width, initial-scale=1">\n' + boot)
    page.write_text(html.replace("<head>", "<head>\n" + boot, 1) if "<head>" in html else doc + html)

    owner_token = secrets.token_urlsafe(24)
    config = {"title": head.get("title", "Choices"), "url": url, "open": bool(a.open), "ownerName": owner,
              "ownerHash": hashlib.sha256(owner_token.encode()).hexdigest(), "meta": hosted_meta}
    (out / "choices-config.json").write_text(json.dumps(config, ensure_ascii=False, indent=1))
    shutil.copy2(ASSETS / "lambda.mjs", out / "lambda.mjs")
    shutil.copytree(ASSETS / "tests", out / "tests")
    (out / "package.json").write_text(json.dumps({"name": f"choices-{slug}", "private": True, "type": "module",
                                                  "scripts": {"test": "node --test tests/*.test.mjs"}}, indent=1))
    (out / "hl.json").write_text(json.dumps({
        "title": head.get("title", "Choices"), "description": head.get("intro", "")[:200], "kind": "choices",
        "slug": slug, "static": "public", "server": "lambda.mjs", "alerts": True, "concurrency": 5}, indent=1))
    save_record(slug, {"slug": slug, "url": url, "dir": str(out), "owner_token": owner_token, "owner": owner,
                       "open": bool(a.open), "links": {}})
    print(f"\nbundle: {out}\nnext:   hlsite deploy {out}\nthen:   hosted.py invite {slug} \"Name\" ...")
    print(f"owner link (keep private; it can close voting): {url}?v={owner_token}")


def cmd_invite(a):
    rec = record(a.slug)
    got = call(rec, "POST", "invite", {"names": a.names})["invited"]
    for v in got:
        rec["links"][v["name"]] = f"{rec['url']}?v={v['token']}"
    save_record(a.slug, rec)
    width = max(len(v["name"]) for v in got)
    for v in got:
        print(f"{v['name']:{width}}  {rec['links'][v['name']]}")


def cmd_links(a):
    rec = record(a.slug)
    for name, link in rec["links"].items():
        print(f"{name}: {link}")
    print(f"(owner) {rec['url']}?v={rec['owner_token']}")


def cmd_status(a):
    rec = record(a.slug)
    d = call(rec, "GET", "export")
    print(f"{d['title']}: {'CLOSED' if d['closed'] else 'open'} · {rec['url']}")
    for v in d["voters"]:
        print(f"  {'✓ voted ' if v['voted'] else ('· opened' if v['opened'] else '  -     ')}  {v['name']}")
    extra = [v for v in d["votes"] if v["id"] == "owner"]
    if extra:
        print("  ✓ voted   " + rec.get("owner", "owner") + " (owner)")


def cmd_votes(a):
    rec = record(a.slug)
    d = call(rec, "GET", "export")
    out = Path(a.out_dir) / "votes"
    out.mkdir(parents=True, exist_ok=True)
    used = set()
    for v in d["votes"]:
        name = (v.get("name") or v["id"]).replace("/", "-")
        while name in used:
            name += "+"
        used.add(name)
        (out / f"{name}.json").write_text(json.dumps({"id": name, "data": {"sections": v["sections"]}}, indent=1))
    print(f"{len(d['votes'])} ballots in {out} (named by voter); run tally.py {a.out_dir} choices.json")


def cmd_state(a, closed: bool):
    rec = record(a.slug)
    call(rec, "POST", "state", {"closed": closed})
    print(f"{rec['url']} is now {'closed' if closed else 'open'} for voting")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build")
    p.add_argument("inputs", nargs="+")
    p.add_argument("--slug", required=True, help="readable start of the URL; a random suffix is added")
    p.add_argument("--exact-slug", action="store_true", help="no random suffix (guessable)")
    p.add_argument("--open", action="store_true", help="anyone with the URL can vote after typing a name")
    p.add_argument("--owner")
    p.set_defaults(fn=cmd_build)
    p = sub.add_parser("invite")
    p.add_argument("slug")
    p.add_argument("names", nargs="+")
    p.set_defaults(fn=cmd_invite)
    for name, fn in (("links", cmd_links), ("status", cmd_status)):
        p = sub.add_parser(name)
        p.add_argument("slug")
        p.set_defaults(fn=fn)
    p = sub.add_parser("votes")
    p.add_argument("slug")
    p.add_argument("out_dir")
    p.set_defaults(fn=cmd_votes)
    for name, closed in (("close", True), ("reopen", False)):
        p = sub.add_parser(name)
        p.add_argument("slug")
        p.set_defaults(fn=lambda a, closed=closed: cmd_state(a, closed))
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
