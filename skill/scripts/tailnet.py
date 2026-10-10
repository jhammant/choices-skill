#!/usr/bin/env python3
"""Private /choices pages on Jon's tailnet, so he can pick from his phone or iPad anywhere.

  tailnet.py build choices.json [section-*.json ...] --slug outstanding [--server orbital]   # one-off page + URL
  tailnet.py votes <slug> <out_dir> [--server orbital]     # export picks for tally.py
  tailnet.py servers                                        # list the configured servers

Live pages (one per workspace; the default for Jon) stream new items to an open page:

  tailnet.py build top.json [section-*.json ...] --live --slug orbital [--server orbital] [--title "..."]
  tailnet.py add <slug> section.json [--owner <session-name>] [--ws <workspace>] [--server orbital]
  tailnet.py resolve <slug> <groupKey> --note "what happened" [--server orbital]   # moves it to the Done section
  tailnet.py remove <slug> <groupKey> [--server orbital]   # deletes a group, its picks and its picks.jsonl lines
  tailnet.py list <slug> [--all] [--server orbital]        # open groups and their pick status
  tailnet.py rebuild <slug> [--server orbital]             # re-render from the sources (e.g. after a template change)

Reading and answering without the page (the voice front end, other sessions):

  tailnet.py show <slug> [<groupKey>] [--brief] [--json] [--all] [--server orbital]
      # the open questions: title, options with pros and cons, current pick and comment (one question with a key)
  tailnet.py pick <slug> <groupKey> <value>[,<value>...] [--comment "..."] [--voter jon] [--dry-run] [--json]
      # validate against the question's options and mode (one / many / rank, rank in order) and save it like a tap
      # on the page: merged into the saved state per question, never touching other questions or voters.
      # Value "-" keeps the current pick and only sets the comment; --comment "" clears the comment.

A live page keeps its sources in <root>/choices/<slug>/src/ (00-top.json plus one file per added section file),
its bookkeeping in live.json (who added each group, what's resolved) and a version counter in version.json, which
the open page polls to show "N new items: tap to load". Saved picks survive every rebuild: they're keyed by section
and group, and `resolve` moves a group's picks with it into the Done section. tailnet_watch.py (loom job
choices-watch) appends newly answered groups to <root>/choices/<slug>/picks.jsonl for Claude to act on.

The page is the normal choices picker plus a small shim (assets/tailnet/shim.js) that stands in for claude.ai's
window.claude: Jon's picks and notes save to the server's own /state/choices-<slug> endpoint (a file on the Mac),
so Claude reads them from disk, with no copying back. Nothing leaves the tailnet: each server is a 127.0.0.1 page
server exposed with `tailscale serve` (tailnet only, never Funnel).

Servers live in ~/.config/choices/tailnet.json:
  {"<name>": {"root": "<dir served>", "base": "<tailnet URL of root>", "port": 8767, "ws": "<workspace>"}}
The default, "orbital", is the triage pageserver (~/dev/orbital/triage, https://ghost.tail22c501.ts.net). Pick the
server that matches the workspace: an Orbital page never goes on another workspace's server, or the reverse.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHIM = HERE.parent / "assets" / "tailnet" / "shim.js"
CONFIG = Path(os.environ.get("CHOICES_TAILNET_CONFIG") or Path.home() / ".config" / "choices" / "tailnet.json")
DEFAULTS = {"orbital": {"root": str(Path.home() / "dev" / "orbital" / "triage"),
                        "base": "https://ghost.tail22c501.ts.net", "port": 8765, "ws": "orbital"}}
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
DONE, EMPTY = "done", "empty"          # section keys the live builder owns
TOP = "00-top.json"

sys.path.insert(0, str(HERE))
import build_choices  # noqa: E402


def fail(msg):
    sys.exit(f"tailnet: {msg}")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def servers() -> dict:
    out = {k: dict(v) for k, v in DEFAULTS.items()}
    if CONFIG.exists():
        for k, v in json.loads(CONFIG.read_text()).items():
            out[k] = {**out.get(k, {}), **v}
    for k, v in out.items():
        v.setdefault("ws", k)
    return out


def server(name: str) -> dict:
    s = servers().get(name)
    if not s:
        fail(f"no server {name!r}; known: {', '.join(servers())} (add one in {CONFIG})")
    return s


def state_key(slug: str) -> str:
    return f"choices-{slug}"


def page_dir(srv: dict, slug: str) -> Path:
    return Path(srv["root"]).expanduser() / "choices" / slug


def state_file(srv: dict, slug: str) -> Path:
    return Path(srv["root"]).expanduser() / "state" / f"{state_key(slug)}.json"


def page_url(srv: dict, slug: str) -> str:
    return f"{srv['base'].rstrip('/')}/choices/{slug}/"


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        fail(f"{path}: invalid JSON: {e}")


def write_json(path: Path, obj, indent=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(obj, indent=indent, ensure_ascii=False) + "\n")
    tmp.chmod(0o600)
    tmp.replace(path)


# ---------------------------------------------------------------- page rendering

def render(srv: dict, slug: str, inputs, *, owner: str, voter: str, live_version=None, quiet=False):
    """Build <root>/choices/<slug>/index.html from choices JSON files and add the tailnet boot (shim)."""
    out = page_dir(srv, slug)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / ".index.html.tmp"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        head, meta = build_choices.build([str(p) for p in inputs], tmp)
    if not quiet:
        print(buf.getvalue().replace(str(tmp), str(out / "index.html")), end="")

    owner = owner or head.get("owner") or "Jon"
    tailnet_meta = dict(meta, hosted=True, owner=owner, invite="")
    html = tmp.read_text()
    old = json.dumps(meta, ensure_ascii=False).replace("</", "<\\/")
    if html.count(old) != 1:
        fail("couldn't find the page META to mark it tailnet-hosted")
    html = html.replace(old, json.dumps(tailnet_meta, ensure_ascii=False).replace("</", "<\\/"))
    cfg = {"key": state_key(slug), "voter": voter, "name": owner,
           "groups": {s["key"]: [g["key"] for g in s["groups"]] for s in meta["sections"]}}
    if live_version is not None:
        cfg.update(live=True, version=live_version)
    cfg_js = json.dumps(cfg, ensure_ascii=False).replace("</", "<\\/")
    boot = (f'<meta name="robots" content="noindex">\n<script>window.CHOICES_TAILNET = {cfg_js};</script>\n'
            f'<script>\n{SHIM.read_text()}</script>\n')
    # The template is a fragment (claude.ai wraps artifacts in a document); give the page a real one.
    doc = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
           '<meta name="viewport" content="width=device-width, initial-scale=1">\n' + boot)
    tmp.write_text(html.replace("<head>", "<head>\n" + boot, 1) if "<head>" in html else doc + html)
    tmp.chmod(0o600)
    tmp.replace(out / "index.html")
    return head, meta


def cmd_build(a):
    srv = server(a.server)
    if a.live:
        return build_live(a, srv)
    base = a.slug.lower().strip("-")
    slug = base if a.exact_slug else f"{base}-{''.join(secrets.choice(ALPHABET) for _ in range(6))}"
    if len(state_key(slug)) > 80:
        fail("slug too long")
    out = page_dir(srv, slug)
    if out.exists() and not a.replace:
        fail(f"{out} exists (use --replace to rebuild the same page; saved picks are kept)")
    if (out / "live.json").exists():
        fail(f"{slug} is a live page: use `add`, `resolve` or `build --live --replace`")
    render(srv, slug, a.inputs, owner=a.owner, voter=a.voter)
    print(f"page:  {out / 'index.html'}\nurl:   {page_url(srv, slug)}   (tailnet only)\n"
          f"state: {state_file(srv, slug)}")
    print(f"picks: python3 {Path(__file__)} votes {slug} <out_dir> --server {a.server}")


# ---------------------------------------------------------------- live pages

@contextlib.contextmanager
def page_lock(d: Path):
    d.mkdir(parents=True, exist_ok=True)
    with open(d / ".lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def load_manifest(d: Path) -> dict:
    m = read_json(d / "live.json")
    if not m:
        fail(f"{d.name} is not a live page (build it with `build --live`)")
    m.setdefault("groups", {})
    m.setdefault("resolved", {})
    return m


def source_files(src: Path) -> list:
    rest = sorted(p for p in src.glob("*.json") if p.name != TOP and not p.name.startswith("."))
    return ([src / TOP] if (src / TOP).exists() else []) + rest


def load_doc(path: Path) -> dict:
    doc = read_json(path)
    if not isinstance(doc, dict):
        fail(f"{path}: expected a JSON object")
    return doc


def ingest_images(doc: dict, origin: Path, src: Path):
    """Copy image files next to the sources, so a rebuild still finds them after the scratch folder is gone."""
    for s in doc.get("sections", []):
        for g in s.get("groups", []):
            for o in g.get("options", []):
                c = o.get("content") or {}
                if c.get("type") != "image" or str(c.get("body", "")).startswith("data:"):
                    continue
                p = Path(c["body"]).expanduser()
                p = p if p.is_absolute() else (origin / p).resolve()
                if not p.exists():
                    fail(f"image not found: {p}")
                name = hashlib.sha1(p.read_bytes()).hexdigest()[:12] + p.suffix.lower()
                (src / "img").mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, src / "img" / name)
                c["body"] = f"img/{name}"


def existing_keys(src: Path):
    sections, groups = set(), {}
    for f in source_files(src):
        for s in load_doc(f).get("sections", []):
            sections.add(s["key"])
            for g in s.get("groups", []):
                groups[g["key"]] = g.get("title", g["key"])
    return sections, groups


def admit(doc: dict, path, src: Path, manifest: dict, *, owner: str, ws: str, fname: str) -> list:
    """Check a section file against the page, fix section-key clashes, record its groups. Returns group titles."""
    build_choices.validate(doc, path)
    secs = doc.get("sections") or []
    have_s, have_g = existing_keys(src)
    seen = {}
    for s in secs:
        for g in s.get("groups", []):
            k = g["key"]
            if k in have_g:
                fail(f"{path}: group key {k!r} is already on the page ({have_g[k]!r}); use a different key")
            if k in seen:
                fail(f"{path}: group key {k!r} appears twice in this file")
            seen[k] = True
    titles = []
    for s in secs:
        key, i = s["key"], 2
        while key in have_s or key in (DONE, EMPTY):
            key, i = f"{s['key']}{i}", i + 1
        if key != s["key"]:
            print(f"note: section key {s['key']!r} is taken on this page; using {key!r}")
            s["key"] = key
        have_s.add(key)
        for g in s.get("groups", []):
            manifest["groups"][g["key"]] = {
                "title": g.get("title", g["key"]), "section": key, "owner": owner, "ws": ws, "added": now_iso(),
                "file": fname, "mode": g.get("mode", "one"),
                "names": {str(o["value"]): o.get("name", str(o["value"])) for o in g.get("options", [])}}
            titles.append(g.get("title", g["key"]))
    return titles


def next_name(src: Path, doc: dict) -> str:
    nums = [int(m.group(1)) for p in src.glob("*.json") if (m := re.match(r"^(\d+)-", p.name))]
    key = (doc.get("sections") or [{}])[0].get("key", "section")
    return f"{max(nums + [0]) + 1:03d}-{key}.json"


def file_for(src: Path, doc: dict, manifest: dict) -> str:
    """Name the next source file after its (possibly renamed) first section and note it on its groups."""
    name = next_name(src, doc)
    for sec in doc.get("sections", []):
        for g in sec.get("groups", []):
            manifest["groups"][g["key"]]["file"] = name
    return name


def assemble(d: Path, manifest: dict) -> Path:
    """Merge the sources into one choices file: open sections in order, resolved groups in a Done section last."""
    src = d / "src"
    files = source_files(src)
    if not files:
        fail(f"{src} has no {TOP}")
    top = load_doc(files[0])
    resolved = manifest["resolved"]
    open_secs, done = [], []
    for f in files:
        for s in load_doc(f).get("sections", []):
            keep = []
            for g in s.get("groups", []):
                if g["key"] in resolved:
                    r = resolved[g["key"]]
                    done.append((r.get("at", ""), dict(g, subtitle=r.get("note") or "Done")))
                else:
                    keep.append(g)
            if keep:
                open_secs.append(dict(s, groups=keep))
    if not open_secs:
        open_secs.append({"key": EMPTY, "title": "Nothing waiting",
                          "intro": "Nothing to decide right now. New items appear here as sessions add them, "
                                   "and this page updates itself.", "groups": []})
    if done:
        done.sort(key=lambda x: x[0], reverse=True)
        open_secs.append({"key": DONE, "title": "Done",
                          "intro": "Resolved items, newest first. Each one says what happened.",
                          "groups": [g for _, g in done]})
    doc = {k: v for k, v in top.items() if k != "sections"}
    doc["sections"] = open_secs
    out = src / ".combined.json"
    write_json(out, doc)
    return out


def current_version(d: Path) -> int:
    return int((read_json(d / "version.json") or {}).get("version", 0))


def rebuild(srv: dict, slug: str, d: Path, manifest: dict, *, added=(), resolved=(), removed=()):
    n = current_version(d) + 1
    combined = assemble(d, manifest)
    render(srv, slug, [combined], owner=manifest.get("owner", "Jon"), voter=manifest.get("voter", "jon"),
           live_version=n, quiet=True)
    v = read_json(d / "version.json") or {}
    entry = {"v": n, "at": now_iso(), "added": list(added)}
    if resolved:
        entry["resolved"] = list(resolved)
    if removed:
        entry["removed"] = list(removed)
    log = (v.get("log") or [])[-49:] + [entry]
    write_json(d / "version.json", {"version": n, "updated": entry["at"], "added": list(added), "log": log})
    write_json(d / "live.json", manifest)
    return n


def build_live(a, srv):
    slug = a.slug.lower().strip("-")
    if not build_choices.KEY_RE.match(slug) or len(state_key(slug)) > 80:
        fail("live slugs are short words like 'orbital' (letters, digits, '-')")
    d = page_dir(srv, slug)
    ws = a.ws or srv["ws"]
    if ws != srv["ws"]:
        fail(f"server {a.server!r} is the {srv['ws']} workspace's; never put {ws} items on it")
    if d.exists() and not a.replace:
        fail(f"{d} exists (live pages grow with `add`; `--replace` resets its sources but keeps picks)")
    with page_lock(d):
        src = d / "src"
        if src.exists():
            shutil.rmtree(src)
        src.mkdir(parents=True)
        src.chmod(0o700)
        old = read_json(d / "live.json") or {}
        manifest = {"slug": slug, "server": a.server, "ws": ws, "owner": a.owner or "Jon", "voter": a.voter,
                    "created": old.get("created") or now_iso(), "groups": {}, "resolved": {}}
        top_path = Path(a.inputs[0])
        top = load_doc(top_path)
        if a.title:
            top["title"] = a.title
        titles = []
        top_secs = top.get("sections") or []
        if top_secs:
            ingest_images(top, top_path.parent.resolve(), src)
            titles += admit(top, top_path, src, manifest, owner=a.session, ws=ws, fname=TOP)
        write_json(src / TOP, top)
        for p in a.inputs[1:]:
            doc = load_doc(Path(p))
            doc = {"sections": doc.get("sections") or []}
            ingest_images(doc, Path(p).parent.resolve(), src)
            titles += admit(doc, p, src, manifest, owner=a.session, ws=ws, fname="")
            write_json(src / file_for(src, doc, manifest), doc)
        n = rebuild(srv, slug, d, manifest, added=titles)
    print(f"live page: {d / 'index.html'}  (version {n}, {len(titles)} questions)")
    print(f"url:   {page_url(srv, slug)}   (tailnet only)\nstate: {state_file(srv, slug)}")
    print(f"add:   python3 {Path(__file__)} add {slug} <section.json> --owner <session> --server {a.server}")


def live_page(a):
    srv = server(a.server)
    d = page_dir(srv, a.slug)
    return srv, d, load_manifest(d)


def cmd_add(a):
    srv, d, manifest = live_page(a)
    ws = a.ws or srv["ws"]
    if ws != srv["ws"] or ws != manifest.get("ws", srv["ws"]):
        fail(f"this page is the {manifest.get('ws', srv['ws'])} workspace's; add {ws} items to the {ws} page instead")
    path = Path(a.section)
    doc = load_doc(path)
    doc = {"sections": doc.get("sections") or []}
    if not doc["sections"]:
        fail(f"{path}: no sections")
    with page_lock(d):
        manifest = load_manifest(d)
        src = d / "src"
        ingest_images(doc, path.parent.resolve(), src)
        titles = admit(doc, path, src, manifest, owner=a.owner or "", ws=ws, fname="")
        if not titles:
            fail(f"{path}: no questions to add")
        write_json(src / file_for(src, doc, manifest), doc)
        n = rebuild(srv, a.slug, d, manifest, added=titles)
    print(f"added {len(titles)} question(s) to {a.slug} (version {n}): " + "; ".join(titles))
    print(f"url: {page_url(srv, a.slug)}")


def migrate_state(srv, slug, fn):
    """Apply fn(sections) to every ballot in the page's state file. fn returns True if it changed anything."""
    f = state_file(srv, slug)
    st = read_json(f)
    if not st:
        return False
    changed = False
    for v in (st.get("votes") or {}).values():
        changed |= bool(fn(v.setdefault("sections", {})))
    if changed:
        write_json(f, st)
    return changed


def mover(gkey: str, dest: str):
    def fn(secs):
        moved = False
        for sk in list(secs):
            if sk == dest:
                continue
            s = secs[sk] or {}
            for field in ("picks", "comments"):
                if gkey in (s.get(field) or {}):
                    val = s[field].pop(gkey)
                    tgt = secs.setdefault(dest, {"picks": {}, "note": "", "comments": {}})
                    tgt.setdefault(field, {})
                    if gkey not in tgt[field]:
                        tgt[field][gkey] = val
                    moved = True
            if moved and not s.get("picks") and not s.get("comments") and not s.get("note"):
                secs.pop(sk, None)  # the emptied stub of the section it left
        return moved
    return fn


def purger(gkey: str):
    def fn(secs):
        hit = False
        for sk in list(secs):
            s, here = secs[sk] or {}, False
            for field in ("picks", "comments"):
                if gkey in (s.get(field) or {}):
                    del s[field][gkey]
                    here = True
            if here and not s.get("picks") and not s.get("comments") and not s.get("note"):
                del secs[sk]  # an emptied section stub; the page recreates it if it still exists
            hit |= here
        return hit
    return fn


def need_group(manifest, gkey):
    if gkey not in manifest["groups"]:
        fail(f"no group {gkey!r} on this page; open ones: "
             + ", ".join(k for k in manifest["groups"] if k not in manifest["resolved"]))
    return manifest["groups"][gkey]


def cmd_resolve(a):
    srv, d, manifest = live_page(a)
    with page_lock(d):
        manifest = load_manifest(d)
        g = need_group(manifest, a.group)
        manifest["resolved"][a.group] = {"note": a.note.strip(), "at": now_iso(), "from": g["section"]}
        migrate_state(srv, a.slug, mover(a.group, DONE))
        n = rebuild(srv, a.slug, d, manifest, resolved=[g["title"]])
        # A page that was mid-save while this ran may have written the old place back; move it again.
        migrate_state(srv, a.slug, mover(a.group, DONE))
    print(f"resolved {a.group} ({g['title']}) on {a.slug}: moved to Done (version {n})")


def cmd_remove(a):
    srv, d, manifest = live_page(a)
    with page_lock(d):
        manifest = load_manifest(d)
        g = need_group(manifest, a.group)
        src = d / "src"
        for f in source_files(src):
            doc = load_doc(f)
            hit = False
            for s in doc.get("sections", []):
                before = len(s.get("groups", []))
                s["groups"] = [x for x in s.get("groups", []) if x["key"] != a.group]
                hit |= len(s["groups"]) != before
            if not hit:
                continue
            doc["sections"] = [s for s in doc["sections"] if s["groups"]]
            if not doc["sections"] and f.name != TOP:
                f.unlink()
            else:
                write_json(f, doc)
        manifest["groups"].pop(a.group, None)
        manifest["resolved"].pop(a.group, None)
        migrate_state(srv, a.slug, purger(a.group))
        pj = d / "picks.jsonl"
        if pj.exists():
            keep = [ln for ln in pj.read_text().splitlines() if ln.strip() and json.loads(ln).get("group") != a.group]
            pj.write_text("".join(ln + "\n" for ln in keep))
        n = rebuild(srv, a.slug, d, manifest, removed=[g["title"]])
        migrate_state(srv, a.slug, purger(a.group))
    print(f"removed {a.group} ({g['title']}) from {a.slug}: sources, picks and picks.jsonl lines (version {n})")


def ballots(state: dict, manifest: dict) -> dict:
    """{voter: {"at": iso, "groups": {gkey: {"pick", "comment", "section"}}, "notes": {sectionKey: text}}}.
    Keyed by group, which is unique on a live page, so a group's answer follows it into Done."""
    home = {k: (DONE if k in manifest.get("resolved", {}) else v.get("section")) for k, v in manifest["groups"].items()}
    out = {}
    for voter, v in ((state or {}).get("votes") or {}).items():
        groups, notes = {}, {}
        for sk, s in (v.get("sections") or {}).items():
            s = s or {}
            if s.get("note"):
                notes[sk] = s["note"]
            for field, name in (("picks", "pick"), ("comments", "comment")):
                for gk, val in (s.get(field) or {}).items():
                    if gk not in home:
                        continue
                    row = groups.setdefault(gk, {"pick": None, "comment": "", "section": home[gk]})
                    if sk == home[gk] or row[name] in (None, "", []):
                        row[name] = val
        out[voter] = {"at": v.get("at", ""), "groups": groups, "notes": notes}
    return out


def answered(row) -> bool:
    return row.get("pick") not in (None, "", []) or bool(row.get("comment"))


def shown(pick, names) -> str:
    if pick in (None, "", []):
        return "-"
    vals = pick if isinstance(pick, list) else [pick]
    return ", ".join(f"{v} {names.get(str(v), '')}".strip() for v in vals)


def cmd_list(a):
    srv, d, manifest = live_page(a)
    b = ballots(read_json(state_file(srv, a.slug)) or {}, manifest)
    resolved = manifest["resolved"]
    rows = [(k, g) for k, g in manifest["groups"].items() if a.all or k not in resolved]
    print(f"{a.slug} ({manifest.get('ws')}): {len(manifest['groups']) - len(resolved)} open, {len(resolved)} done, "
          f"version {current_version(d)}  {page_url(srv, a.slug)}")
    for k, g in rows:
        marks = []
        for voter, bv in b.items():
            r = bv["groups"].get(k)
            if r and answered(r):
                who = f"{voter}: " if len(b) > 1 else ""
                c = f'  comment: "{r["comment"][:90]}"' if r.get("comment") else ""
                marks.append(f"{who}picked {shown(r['pick'], g.get('names', {}))}{c}")
        status = "; ".join(marks) or "open"
        done = f"  [done: {resolved[k]['note'][:60]}]" if k in resolved else ""
        print(f"  {k:<10} {g['title'][:60]:<60}  {status}{done}  ({g.get('owner') or '-'})")
    for voter, bv in b.items():
        for sk, note in bv["notes"].items():
            print(f"  note on {sk}: \"{note[:120]}\"")


def cmd_rebuild(a):
    srv, d, manifest = live_page(a)
    with page_lock(d):
        n = rebuild(srv, a.slug, d, load_manifest(d))
    print(f"rebuilt {a.slug} (version {n}) {page_url(srv, a.slug)}")


# ---------------------------------------------------------------- show / pick (no page needed)

def questions(srv: dict, slug: str, *, voter: str = "jon", include_done: bool = False) -> dict:
    """Every question on a live page, in page order, with its options and the voter's current answer.

    {"slug", "url", "ws", "open": n, "done": n, "questions": [{"key", "title", "subtitle", "section",
     "section_title", "mode", "owner", "done", "done_note", "options": [{"value", "name", "blurb", "pros", "cons",
     "current", "content"}], "pick", "pick_name", "comment"}]}"""
    d = page_dir(srv, slug)
    manifest = load_manifest(d)
    resolved = manifest["resolved"]
    mine = ballots(read_json(state_file(srv, slug)) or {}, manifest).get(voter, {"groups": {}})["groups"]
    out = []
    for f in source_files(d / "src"):
        for s in load_doc(f).get("sections", []):
            for g in s.get("groups", []):
                k = g["key"]
                if k not in manifest["groups"] or (k in resolved and not include_done):
                    continue
                row = mine.get(k) or {}
                names = {str(o["value"]): o.get("name", str(o["value"])) for o in g.get("options", [])}
                pick = row.get("pick")
                vals = pick if isinstance(pick, list) else ([] if pick in (None, "") else [pick])
                out.append({
                    "key": k, "title": g.get("title", k), "subtitle": g.get("subtitle", ""),
                    "section": s["key"], "section_title": s.get("title", ""), "mode": g.get("mode", "one"),
                    "owner": manifest["groups"][k].get("owner", ""), "done": k in resolved,
                    "done_note": (resolved.get(k) or {}).get("note", ""),
                    "options": [{"value": str(o["value"]), "name": o.get("name", str(o["value"])),
                                 "blurb": o.get("blurb", ""), "pros": list(o.get("pros") or []),
                                 "cons": list(o.get("cons") or []), "current": bool(o.get("current")),
                                 "content": (o.get("content") or {}).get("type", "")}
                                for o in g.get("options", [])],
                    "pick": pick, "pick_name": [names.get(str(v), "") for v in vals],
                    "comment": row.get("comment", "") or ""})
    out.sort(key=lambda q: q["done"])  # open first, page order kept within each (sort is stable)
    return {"slug": slug, "url": page_url(srv, slug), "ws": manifest.get("ws", srv["ws"]),
            "open": len(manifest["groups"]) - len(resolved), "done": len(resolved), "questions": out}


def question_text(q: dict, *, brief: bool = False) -> str:
    mode = {"one": "pick one", "many": "pick any", "rank": "rank in order"}.get(q["mode"], q["mode"])
    head = f"{q['key']}: {q['title']}  ({mode})"
    if q["done"]:
        head += f"  [done: {q['done_note']}]"
    status = f"picked {shown(q['pick'], {o['value']: o['name'] for o in q['options']})}" \
        if q["pick"] not in (None, "", []) else "no pick yet"
    if q["comment"]:
        status += f'; comment: "{q["comment"]}"'
    if brief:
        return f"{head}  -  {status}"
    lines = [head]
    if q["subtitle"]:
        lines.append(f"  {q['subtitle']}")
    for o in q["options"]:
        tag = " (current)" if o["current"] else ""
        lines.append(f"  {o['value']}. {o['name']}{tag}" + (f": {o['blurb']}" if o["blurb"] else ""))
        lines += [f"     + {p}" for p in o["pros"]] + [f"     - {c}" for c in o["cons"]]
    lines.append(f"  Now: {status}")
    return "\n".join(lines)


def cmd_show(a):
    srv = server(a.server)
    data = questions(srv, a.slug, voter=a.voter, include_done=a.all or bool(a.group))
    if a.group:
        hit = [q for q in data["questions"] if q["key"] == a.group]
        if not hit:
            fail(f"no question {a.group!r} on {a.slug}; open ones: "
                 + ", ".join(q["key"] for q in data["questions"] if not q["done"]))
        data["questions"] = hit
    if a.json:
        print(json.dumps(data, indent=1, ensure_ascii=False))
        return
    if not a.group:
        print(f"{a.slug} ({data['ws']}): {data['open']} open, {data['done']} done  {data['url']}")
    for q in data["questions"]:
        print(question_text(q, brief=a.brief))
        if not a.brief:
            print()


def parse_pick(q: dict, raw: str):
    """Turn "b" / "A,C" / "sso, docs" into the saved shape for the question's mode, or fail with the reason."""
    by_value = {o["value"].lower(): o["value"] for o in q["options"]}
    vals = [v.strip() for v in str(raw).split(",") if v.strip()]
    if not vals:
        fail(f"{q['key']}: no value given; options: {', '.join(o['value'] for o in q['options'])}")
    bad = [v for v in vals if v.lower() not in by_value]
    if bad:
        fail(f"{q['key']}: {', '.join(bad)} is not an option; options: "
             + ", ".join(f"{o['value']} ({o['name']})" for o in q["options"]))
    vals = [by_value[v.lower()] for v in vals]
    if len(set(vals)) != len(vals):
        fail(f"{q['key']}: a value appears twice")
    if q["mode"] == "one":
        if len(vals) != 1:
            fail(f"{q['key']} is pick-one: give exactly one of {', '.join(o['value'] for o in q['options'])}")
        return vals[0]
    return vals  # many: any subset; rank: in order of preference (a partial ranking is what the page allows too)


def utc_ms() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _state_url(srv: dict, slug: str) -> str:
    return f"http://127.0.0.1:{srv.get('port', 8765)}/state/{state_key(slug)}"


def save_answer(srv: dict, slug: str, *, voter: str, section: str, group: str, pick=None, comment=None) -> str:
    """Merge one question's answer into the saved state the way the page's shim does: only this question's pick
    and/or comment change; every other question, section note and voter keeps the server's copy. Saves through the
    page server's /state endpoint (so it is the same write path as a tap), or atomically to the file when the server
    is down. Returns "server" or "file"."""
    import urllib.error
    import urllib.request

    url = _state_url(srv, slug)
    origin = f"http://127.0.0.1:{srv.get('port', 8765)}"

    def fetch():
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"Cache-Control": "no-store"}),
                                        timeout=5) as r:
                return json.loads(r.read() or b"{}"), True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"votes": {}, "closed": False}, True
            return None, False
        except (urllib.error.URLError, OSError, ValueError):
            return None, False

    state, via_server = fetch()
    if state is None:
        state = read_json(state_file(srv, slug)) or {"votes": {}, "closed": False}
    if state.get("closed"):
        fail(f"{slug} is closed to new picks")
    votes = state.setdefault("votes", {})
    ballot = votes.setdefault(voter, {"sections": {}})
    sec = ballot.setdefault("sections", {}).setdefault(section, {"picks": {}, "note": "", "comments": {}})
    sec.setdefault("picks", {})
    sec.setdefault("comments", {})
    sec.setdefault("note", "")
    if pick is not None:
        sec["picks"][group] = pick
    if comment is not None:
        if comment.strip():
            sec["comments"][group] = comment.strip()[:1000]
        else:
            sec["comments"].pop(group, None)
    ballot["at"] = utc_ms()
    if via_server:
        body = json.dumps(state).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Origin": origin})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                if r.status == 200:
                    return "server"
        except (urllib.error.URLError, OSError):
            pass
    write_json(state_file(srv, slug), state)
    return "file"


def cmd_pick(a):
    srv = server(a.server)
    d = page_dir(srv, a.slug)
    with page_lock(d):
        data = questions(srv, a.slug, voter=a.voter, include_done=True)
        hit = [q for q in data["questions"] if q["key"] == a.group]
        if not hit:
            fail(f"no question {a.group!r} on {a.slug}; open ones: "
                 + ", ".join(q["key"] for q in data["questions"] if not q["done"]))
        q = hit[0]
        if q["done"]:
            fail(f"{a.group} ({q['title']}) is already done: {q['done_note']}")
        keep = str(a.value).strip() == "-"
        if keep and a.comment is None:
            fail("'-' keeps the current pick, so give a --comment")
        pick = None if keep else parse_pick(q, a.value)
        names = {o["value"]: o["name"] for o in q["options"]}
        final = q["pick"] if keep else pick
        vals = final if isinstance(final, list) else ([] if final in (None, "") else [final])
        result = {"ok": True, "slug": a.slug, "group": q["key"], "title": q["title"], "section": q["section"],
                  "mode": q["mode"], "voter": a.voter, "pick": final, "pick_name": [names.get(v, "") for v in vals],
                  "comment": (a.comment.strip()[:1000] if a.comment is not None else q["comment"]),
                  "saved": False}
        if not a.dry_run:
            result["via"] = save_answer(srv, a.slug, voter=a.voter, section=q["section"], group=q["key"],
                                        pick=pick, comment=a.comment)
            result["saved"] = True
    if a.json:
        print(json.dumps(result, ensure_ascii=False))
        return
    what = shown(result["pick"], names)
    verb = "would save" if a.dry_run else "saved"
    c = f'; comment: "{result["comment"]}"' if result["comment"] else ""
    print(f"{verb} {what} on {q['key']} ({q['title']}) for {a.voter}{c}")


# ---------------------------------------------------------------- picks out

def cmd_votes(a):
    srv = server(a.server)
    f = state_file(srv, a.slug)
    if not f.exists():
        fail(f"no picks saved yet ({f})")
    d = json.loads(f.read_text())
    out = Path(a.out_dir) / "votes"
    out.mkdir(parents=True, exist_ok=True)
    for vid, v in (d.get("votes") or {}).items():
        (out / f"{vid}.json").write_text(json.dumps({"id": vid, "data": {"sections": v.get("sections", {})}}, indent=1))
    print(f"{len(d.get('votes') or {})} ballot(s) in {out}, last saved {max((v.get('at', '') for v in (d.get('votes') or {}).values()), default='never')}")


def cmd_servers(_a):
    for name, s in servers().items():
        lives = sorted(p.parent.name for p in (Path(s["root"]).expanduser() / "choices").glob("*/live.json"))
        print(f"{name} [{s['ws']}]: {s['base']}  <- {s['root']}" + (f"   live: {', '.join(lives)}" if lives else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build")
    p.add_argument("inputs", nargs="+")
    p.add_argument("--slug", required=True, help="readable start of the URL; a random suffix is added (not with --live)")
    p.add_argument("--exact-slug", action="store_true")
    p.add_argument("--live", action="store_true", help="a live page: exact slug, sources kept so `add` can grow it")
    p.add_argument("--title", help="override the first file's title")
    p.add_argument("--session", default="", help="live: the session that owns the seeded questions")
    p.add_argument("--ws", help="live: workspace (must match the server's)")
    p.add_argument("--replace", action="store_true", help="rebuild an existing page in place (picks are kept)")
    p.add_argument("--server", default="orbital")
    p.add_argument("--owner", help="the decider's display name (default Jon)")
    p.add_argument("--voter", default="jon", help="ballot id for the person picking (solo pages)")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("add", help="add a section file's questions to a live page")
    p.add_argument("slug")
    p.add_argument("section")
    p.add_argument("--owner", help="the Claude session adding it (lands in picks.jsonl so it can act)")
    p.add_argument("--ws", help="workspace of these items; must match the page's")
    p.add_argument("--server", default="orbital")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("resolve", help="move a question into the page's Done section")
    p.add_argument("slug")
    p.add_argument("group")
    p.add_argument("--note", required=True, help="what happened, shown under the question")
    p.add_argument("--server", default="orbital")
    p.set_defaults(fn=cmd_resolve)

    p = sub.add_parser("remove", help="delete a question, its picks and its picks.jsonl lines")
    p.add_argument("slug")
    p.add_argument("group")
    p.add_argument("--server", default="orbital")
    p.set_defaults(fn=cmd_remove)

    p = sub.add_parser("list", help="open questions and their pick status")
    p.add_argument("slug")
    p.add_argument("--all", action="store_true", help="include Done")
    p.add_argument("--server", default="orbital")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("rebuild", help="re-render a live page from its sources")
    p.add_argument("slug")
    p.add_argument("--server", default="orbital")
    p.set_defaults(fn=cmd_rebuild)

    p = sub.add_parser("show", help="open questions with options, pros and cons, and the current pick")
    p.add_argument("slug")
    p.add_argument("group", nargs="?", help="just this question")
    p.add_argument("--brief", action="store_true", help="one line per question")
    p.add_argument("--json", action="store_true")
    p.add_argument("--all", action="store_true", help="include Done")
    p.add_argument("--voter", default="jon")
    p.add_argument("--server", default="orbital")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("pick", help="answer a question without the page (merged like a tap)")
    p.add_argument("slug")
    p.add_argument("group")
    p.add_argument("value", help="option value; comma-separated for many/rank (rank in order); '-' = comment only")
    p.add_argument("--comment", help="free text for this question ('' clears it)")
    p.add_argument("--voter", default="jon")
    p.add_argument("--dry-run", action="store_true", help="validate only")
    p.add_argument("--json", action="store_true")
    p.add_argument("--server", default="orbital")
    p.set_defaults(fn=cmd_pick)

    p = sub.add_parser("votes")
    p.add_argument("slug")
    p.add_argument("out_dir")
    p.add_argument("--server", default="orbital")
    p.set_defaults(fn=cmd_votes)
    p = sub.add_parser("servers")
    p.set_defaults(fn=cmd_servers)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
