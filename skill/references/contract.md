# choices JSON contract

One file, or several that get merged: the first file supplies `title`, `intro`, `mode` and `deadline`, and every
file contributes `sections` (section keys must be unique across files).

```json
{
  "title": "Docs homepage direction",
  "intro": "Pick a direction for each part. Notes are welcome. Mix-and-match is fine.",
  "mode": "solo",
  "deadline": "Friday 10 Oct",
  "sections": [
    {
      "key": "hero",
      "title": "Hero",
      "intro": "First screen of the docs site.",
      "groups": [
        {
          "key": "layout",
          "title": "Hero layout",
          "subtitle": "What a new visitor sees first",
          "mode": "one",
          "minWidth": 260,
          "options": [
            {
              "value": "A",
              "name": "Code-first",
              "blurb": "A live query and its result above the fold.",
              "current": true,
              "pros": ["Shows the product immediately"],
              "cons": ["Intimidating for non-engineers"],
              "content": { "type": "svg", "body": "<svg viewBox=\"0 0 320 200\" xmlns=\"http://www.w3.org/2000/svg\">…</svg>" }
            }
          ]
        }
      ]
    }
  ]
}
```

## Fields

| Field | Where | Notes |
|---|---|---|
| `title` | top | Page name (also the browser tab). A short noun phrase. |
| `intro` | top | One or two sentences: what's being decided and how to use the page. |
| `mode` | top | `solo` (tallies hidden until a second person votes), `team` (tallies always shown), or `public` (no saving; for people outside the org, who send back "Copy my choices"). |
| `owner` | top, optional | Who `public` voters send their choices to, e.g. "Sam". |
| `ask` | top, optional | One extra sentence for the invite message (e.g. "Mostly need a steer on the architecture"). |
| `deadline` | top, optional | Shown as "Please choose by …" and included in the invite. |
| `key` | section, group | Letters, digits, `_`, `-`, starting with a letter. Used in saved data, so keep them stable across rebuilds. |
| `mode` | group | `one`, `many` or `rank`. |
| `minWidth` | group, optional | Card minimum width in px. Defaults by content type (code 340, text 280, svg 240, …). |
| `value` | option | Short and stable: "A"/"B"/"C" for alternatives, or ids like "SSO" for `many`/`rank` items. 1–2 character values show as letters. |
| `name`, `blurb` | option | Name of 2–5 words, blurb of one line. |
| `current` | option, optional | `true` marks today's approach with a "Current" tag. |
| `pros`, `cons` | option, optional | 1–3 short items each. Make them honest and specific. |
| `content` | option, optional | See below. Omit it for plain text cards (`rank`/`many` items often need no visual). |

## Content types

| `type` | `body` | Notes |
|---|---|---|
| `svg` | inline `<svg …>` | Give it a `viewBox`. Ids are auto-prefixed. Use a light background: cards show art on a light surface in both themes. |
| `html` | static HTML with inline styles | No scripts, links or form controls (the builder rejects them). Good for quick UI mocks. |
| `text` | plain text | Newlines are kept. Use it for messaging, names and short copy. |
| `markdown` | a small subset | Paragraphs, `-` lists, `#` headings, `**bold**`, `*italic*` and `` `code` ``. |
| `code` | source | Add `"lang": "ts"` for the label. Shown as a dark monospace block. |
| `mermaid` | diagram source | The Artifact viewer renders Mermaid natively, and a pinned cdnjs fallback draws it anywhere else. |
| `image` | a file path | Relative to the JSON file. It's embedded as a data URI and downsized to 1200px. |

## Helper prompt for fan-out (one section per agent)

> Read `SKILL_DIR/references/contract.md` and `SKILL_DIR/references/options-craft.md`. Write ONE file,
> `<scratch>/section-<key>.json`, with `{"sections": [ … one section … ]}` for: <what the section decides,
> constraints, current state>. Use <content type>. Make the options differ along a real axis, give them the same
> fidelity, give each one-line pros and cons, and mark `current` where one exists. Validate with
> `python3 SKILL_DIR/scripts/build_choices.py <file> -o /tmp/x.html`, then reply with one line.
