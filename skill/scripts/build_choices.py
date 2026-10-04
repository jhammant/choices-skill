#!/usr/bin/env python3
"""Build a /choices picker page from one or more choices JSON files.

Usage:
  build_choices.py choices.json [more.json ...] -o out.html [--screenshot out.png]

Several input files are merged in order: the first supplies title/intro/mode, and every file's sections are
appended. That lets parallel helpers each write one section file. See references/contract.md for the format.
"""
import argparse
import base64
import html
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "assets" / "template.html"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MODES = {"one", "many", "rank"}
TYPES = {"svg", "html", "text", "markdown", "code", "mermaid", "image", "none"}
DEFAULT_MIN = {"svg": 240, "html": 280, "text": 280, "markdown": 300, "code": 340, "mermaid": 300, "image": 260, "none": 220}
KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,40}$")
# The Artifact viewer renders <pre class="mermaid"> natively. This fallback draws any diagram it hasn't processed
# (local previews, other hosts). Mermaid marks processed nodes with data-processed, so nothing is drawn twice.
MERMAID_FALLBACK = """<script src="https://cdnjs.cloudflare.com/ajax/libs/mermaid/11.4.0/mermaid.min.js"></script>
<script>
window.addEventListener("load", function () {
  setTimeout(function () {
    var todo = Array.prototype.slice.call(document.querySelectorAll("pre.mermaid")).filter(function (p) {
      return !p.querySelector("svg") && !p.getAttribute("data-processed");
    });
    if (todo.length && window.mermaid) {
      window.mermaid.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "strict" });
      window.mermaid.run({ nodes: todo });
    }
  }, 600);
});
</script>"""


def fail(msg):
    sys.exit(f"choices: {msg}")


def esc(s):
    return html.escape(str(s or ""), quote=True)


def prefix_ids(svg, prefix):
    for i in sorted(set(re.findall(r'\bid="([^"]+)"', svg)), key=len, reverse=True):
        new = f"{prefix}-{i}"
        svg = re.sub(rf'\bid="{re.escape(i)}"', f'id="{new}"', svg)
        svg = svg.replace(f"url(#{i})", f"url(#{new})")
        svg = re.sub(rf'href="#{re.escape(i)}"', f'href="#{new}"', svg)
    return svg


def inline_md(text):
    t = esc(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return t


def markdown(src):
    out, para, items = [], [], []

    def flush():
        if para:
            out.append("<p>" + inline_md(" ".join(para)) + "</p>")
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{inline_md(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for line in str(src).splitlines():
        s = line.strip()
        if not s:
            flush()
        elif s.startswith(("- ", "* ")):
            if para:
                flush()
            items.append(s[2:])
        elif s.startswith("#"):
            flush()
            out.append("<h4>" + inline_md(s.lstrip("#").strip()) + "</h4>")
        else:
            if items:
                flush()
            para.append(s)
    flush()
    return "".join(out)


def image_data_uri(path, base):
    p = Path(path)
    if not p.is_absolute():
        p = (base / p).resolve()
    if not p.exists():
        fail(f"image not found: {p}")
    try:
        from PIL import Image

        im = Image.open(p)
        im.thumbnail((1200, 1200))
        buf = io.BytesIO()
        fmt = "PNG" if im.mode in ("RGBA", "LA", "P") else "JPEG"
        im.save(buf, fmt, **({"quality": 85} if fmt == "JPEG" else {"optimize": True}))
        mime = "image/png" if fmt == "PNG" else "image/jpeg"
        data = buf.getvalue()
    except ImportError:
        data = p.read_bytes()
        mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def render_content(content, prefix, base):
    if not content:
        return ""
    kind = content.get("type", "none")
    body = content.get("body", "")
    if kind == "svg":
        svg = re.sub(r"<\?xml[^>]*>", "", body).strip()
        if not svg.startswith("<svg"):
            fail(f"svg content must start with <svg ({prefix})")
        svg = re.sub(r"<svg\b", '<svg aria-hidden="true" focusable="false"', svg, count=1)
        return prefix_ids(svg, prefix)
    if kind == "html":
        if re.search(r"<(script|iframe|object|embed|form|button|a|input|select|textarea)\b", body, re.I):
            fail(f"html content must be static: no scripts, links or form controls inside an option ({prefix})")
        return f'<div class="html">{prefix_ids(body, prefix)}</div>'
    if kind == "text":
        return f'<div class="text">{esc(body)}</div>'
    if kind == "markdown":
        return f'<div class="md">{markdown(body)}</div>'
    if kind == "code":
        lang = content.get("lang", "")
        label = f'<span class="lang">{esc(lang)}</span>' if lang else ""
        return f"{label}<pre><code>{esc(body)}</code></pre>"
    if kind == "mermaid":
        return f'<pre class="mermaid">{esc(body)}</pre>'
    if kind == "image":
        alt = esc(content.get("alt", ""))
        return f'<img src="{image_data_uri(body, base)}" alt="{alt}">'
    return ""


def validate(doc, src):
    for s in doc.get("sections", []):
        if not KEY_RE.match(str(s.get("key", ""))):
            fail(f"{src}: section key {s.get('key')!r} must be letters/digits/_/- and start with a letter")
        for g in s.get("groups", []):
            if not KEY_RE.match(str(g.get("key", ""))):
                fail(f"{src}: group key {g.get('key')!r} in section {s['key']} is invalid")
            mode = g.get("mode", "one")
            if mode not in MODES:
                fail(f"{src}: group {s['key']}/{g['key']} mode must be one of {sorted(MODES)}")
            opts = g.get("options", [])
            if len(opts) < 2:
                fail(f"{src}: group {s['key']}/{g['key']} needs at least 2 options")
            values = [str(o.get("value", "")) for o in opts]
            if len(set(values)) != len(values) or not all(values):
                fail(f"{src}: group {s['key']}/{g['key']} option values must be unique and non-empty")
            for o in opts:
                kind = (o.get("content") or {}).get("type", "none")
                if kind not in TYPES:
                    fail(f"{src}: option {s['key']}/{g['key']}/{o['value']} has unknown content type {kind!r}")


def option_html(skey, g, o, n, base):
    mode = g.get("mode", "one")
    gid = f"{skey}-{g['key']}"
    oid = f"{gid}-{re.sub(r'[^A-Za-z0-9_-]', '', str(o['value']))}"
    itype = "radio" if mode == "one" else "checkbox"
    content = render_content(o.get("content"), f"c{n}", base)
    art = f'<span class="art">{content}</span>' if content else ""
    current = '<span class="current">Current</span>' if o.get("current") else ""
    blurb = f'<span class="blurb">{esc(o.get("blurb"))}</span>' if o.get("blurb") else ""
    pros = o.get("pros") or []
    cons = o.get("cons") or []
    pc = ""
    if pros or cons:
        pc = '<ul class="pc">' + "".join(f'<li class="p">{esc(p)}</li>' for p in pros) + "".join(
            f'<li class="c">{esc(c)}</li>' for c in cons) + "</ul>"
    letter = f'<span class="letter">{esc(o["value"])}</span>' if len(str(o["value"])) <= 2 else ""
    name = esc(o.get("name", o["value"]))
    return f"""
        <div class="cell">
          <label class="opt" for="{oid}" data-comment-target>
            <input type="{itype}" class="sr-only" name="{gid}" id="{oid}" value="{esc(o['value'])}" data-s="{skey}" data-g="{g['key']}">
            <span class="pickmark" aria-hidden="true"></span>
            {art}
            <span class="opt-text">
              <span class="opt-head">{letter}<span class="opt-name">{name}</span>{current}</span>
              {blurb}{pc}
              <span class="tally" data-s="{skey}" data-g="{g['key']}" data-v="{esc(o['value'])}"><span class="t"></span><span class="bar"><span></span></span></span>
            </span>
          </label>
          <button type="button" class="cmt" data-for="{oid}" hidden>Comment on {esc(o['value']) if letter else name}</button>
        </div>"""


def section_html(s, counter, base):
    blocks = []
    for g in s["groups"]:
        mode = g.get("mode", "one")
        hint = {"one": "pick one", "many": "pick any", "rank": "click in order of preference"}[mode]
        kinds = {(o.get("content") or {}).get("type", "none") for o in g["options"]}
        min_w = g.get("minWidth") or max(DEFAULT_MIN.get(k, 240) for k in kinds)
        opts = []
        for o in g["options"]:
            counter[0] += 1
            opts.append(option_html(s["key"], g, o, counter[0], base))
        sub = f'<p class="sub">{esc(g.get("subtitle"))}</p>' if g.get("subtitle") else ""
        blocks.append(f"""
      <div class="group">
        <h3>{esc(g['title'])}<span class="hint">{hint}</span></h3>{sub}
        <fieldset class="opts" data-mode="{mode}" style="--min: {int(min_w)}px">
          <legend class="sr-only">{esc(g['title'])}</legend>{''.join(opts)}
        </fieldset>
      </div>""")
    intro = f"<p>{esc(s.get('intro'))}</p>" if s.get("intro") else ""
    return f"""
  <section class="section" id="{s['key']}" aria-labelledby="h-{s['key']}">
    <header data-comment-target><h2 id="h-{s['key']}">{esc(s['title'])}</h2>{intro}
      <button type="button" class="cmt cmt-section" data-for="h-{s['key']}" hidden>Comment on this section</button></header>{''.join(blocks)}
    <div class="note">
      <label for="note-{s['key']}">Notes on “{esc(s['title'])}”</label>
      <textarea id="note-{s['key']}" data-note="{s['key']}" maxlength="1000" placeholder="Mix-and-match, changes, or why"></textarea>
      <div class="others" id="others-{s['key']}"></div>
    </div>
  </section>"""


def invite_message(head, url, questions):
    minutes = max(2, round(questions * 0.5))
    mode = head.get("mode", "solo")
    lines = [f"{head.get('title', 'Choices')}: I'd love your view (about {minutes} min)."]
    if head.get("ask"):
        lines.append(head["ask"])
    if mode == "public":
        lines.append(f"Open {url}, pick your favourite in each section (notes welcome), then press "
                     f"\"Copy my choices\" at the bottom and send them to {head.get('owner', 'me')}.")
    else:
        lines.append(f"Open {url} and click your favourite in each section. Notes are welcome. "
                     "Your choices save automatically and you'll see everyone's votes as they come in.")
    if head.get("deadline"):
        lines.append(f"Please choose by {head['deadline']}.")
    return "\n".join(lines)


def build(inputs, out, invite_url=None):
    docs = []
    for path in inputs:
        p = Path(path)
        try:
            doc = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            fail(f"{p}: invalid JSON: {e}")
        validate(doc, p)
        docs.append((doc, p.parent.resolve()))
    head = docs[0][0]
    sections, keys = [], set()
    for doc, base in docs:
        for s in doc.get("sections", []):
            if s["key"] in keys:
                fail(f"duplicate section key {s['key']!r} across input files")
            keys.add(s["key"])
            sections.append((s, base))
    if not sections:
        fail("no sections found")
    counter = [0]
    body = "".join(section_html(s, counter, base) for s, base in sections)
    toc = "".join(f'<a href="#{s["key"]}" data-toc="{s["key"]}">{esc(s["title"])}</a>' for s, _ in sections)
    questions = sum(len(s["groups"]) for s, _ in sections)
    if head.get("mode", "solo") not in {"solo", "team", "public"}:
        fail("top-level mode must be solo, team or public")
    meta = {
        "mode": head.get("mode", "solo"),
        "owner": head.get("owner", ""),
        "invite": invite_message(head, invite_url, questions) if invite_url else "",
        "sections": [{
            "key": s["key"], "title": s["title"],
            "groups": [{"key": g["key"], "title": g["title"], "mode": g.get("mode", "one"),
                        "names": {str(o["value"]): o.get("name", str(o["value"])) for o in g["options"]}}
                       for g in s["groups"]],
        } for s, _ in sections],
    }
    intro_bits = [f"<p>{esc(head.get('intro'))}</p>"] if head.get("intro") else []
    if head.get("deadline"):
        intro_bits.append(f"<p><strong>Please choose by {esc(head['deadline'])}.</strong></p>")
    page = (
        TEMPLATE.read_text()
        .replace("{{TITLE}}", esc(head.get("title", "Choices")))
        .replace("{{INTRO}}", "".join(intro_bits))
        .replace("{{TOC}}", toc)
        .replace("{{SECTIONS}}", body)
        .replace("{{MERMAID}}", MERMAID_FALLBACK if 'class="mermaid"' in body else "")
        .replace("{{META}}", json.dumps(meta, ensure_ascii=False).replace("</", "<\\/"))
    )
    Path(out).write_text(page)
    groups = sum(len(s["groups"]) for s, _ in sections)
    options = sum(len(g["options"]) for s, _ in sections for g in s["groups"])
    print(f"wrote {out}: {len(sections)} sections, {groups} questions, {options} options, {Path(out).stat().st_size // 1024} KB")
    if meta["invite"]:
        print("\n--- invite message ---\n" + meta["invite"] + "\n----------------------")


def screenshot(page, png):
    if not Path(CHROME).exists() and not shutil.which("google-chrome"):
        print("screenshot skipped: Chrome not found")
        return
    exe = CHROME if Path(CHROME).exists() else shutil.which("google-chrome")
    subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1280,2400",
                    "--virtual-time-budget=6000", f"--screenshot={png}", f"file://{Path(page).resolve()}"],
                   capture_output=True, check=False)
    print(f"screenshot: {png}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--screenshot")
    ap.add_argument("--invite-url", help="the published artifact URL; adds an 'Invite your people' panel with a copyable message for the owner")
    a = ap.parse_args()
    build(a.inputs, a.out, a.invite_url)
    if a.screenshot:
        screenshot(a.out, a.screenshot)


if __name__ == "__main__":
    main()
