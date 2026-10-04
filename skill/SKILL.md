---
name: choices
description: Show 2–4 genuinely different options for a decision side by side, publish them as a tap-to-pick page where the decider (or a whole team, with live vote tallies and per-option comments) chooses, share it with their people (invite message, Slack post, email drafts), then read the picks and comments back and turn them into a decision record and build spec. Use whenever the user types /choices or /choice, says "choices" or "a choice page", says "show me options", "give me a few versions/directions", "mock up some alternatives", "which approach should we take", "help me decide between", "let the team vote", "get sign-off on a direction", or is about to settle a design, architecture, positioning/messaging, naming, pricing, deck-storyline, roadmap or tone question that would be easier to judge by seeing alternatives, even if they never say "choices".
---

# /choices: options, picker, decision

This turns "which way should we go?" into a short, repeatable loop: **frame → generate options → publish a picker → read
the picks → record the decision → hand off**. It works because the decider compares real, same-format alternatives
instead of reading prose, the clicks are saved where Claude can read them back (no transcription), and the result
lands as a decision record and spec the next person can build from.

`SKILL_DIR` below means this skill's folder (where this file lives).

## 1. Frame (one short message, then go)

Work out, from the conversation and context first:
- **The questions.** One page can hold several decisions. Split a big decision into 1–6 sections, each with 1–4 questions.
- **Who decides.** Solo (the user) or **team** (several people vote; the page shows tallies and everyone's notes).
- **What exists today.** If there's a current approach, it becomes one option marked `current`, so choosing it
  means "no change" and the cost of change stays visible.
- **Constraints and deadline** (budget, stack, brand, date).

Ask at most one compact question, only for what you truly can't infer. Otherwise state your assumptions in a line and build.

## 2. Generate the options

Read `references/options-craft.md` before writing options. It's what separates useful choices from three versions of
the same thing. In short: options differ along a real axis; include the current state where one exists; give
everything the same fidelity and format; give each option a one-line name and blurb with honest pros and cons; never
include a strawman.

Pick the content type that lets the decider judge fastest:

| Decision about | Content type |
|---|---|
| UI, layout, visual direction, slide look | `svg` mock (or a static `html` mock) |
| Architecture, flow, process | `mermaid` diagram plus pros/cons |
| Messaging, positioning, email or post tone, naming | `text` or `markdown` (same length across options) |
| API shape, code approach, config | `code` with `lang` |
| Screenshots or existing art | `image` (a path; it gets embedded) |

Question modes: `one` (pick one), `many` (tick all that apply), `rank` (click in order of preference, e.g. roadmap items).

## 3. Write the choices file

Write JSON as described in `references/contract.md` to a scratch folder (the session scratchpad, not the repo,
unless asked). For big sets, fan out: give each helper agent one section and the contract, have each write
`section-<key>.json`, then pass all the files to the builder, which merges them in order.

## 4. Build and look once

```bash
python3 "$SKILL_DIR/scripts/build_choices.py" choices.json [section-*.json ...] -o choices.html --screenshot check.png
```

The builder validates the file (keys, modes, unique values, content types, static HTML only) and fails with a clear
message. View `check.png` once and fix anything clearly broken (clipped art, unreadable text). Don't loop.

## 5. Publish and share

**Choose the audience**, because it decides how the page is published:
- **The user alone, or colleagues in their Claude organization**: top-level `mode` is `solo` or `team`. Picks save
  automatically and everyone sees live tallies and each other's notes. Publish with these capabilities exactly. They
  give each voter their own ballot, everyone sees the tallies, and only editors can close voting:

  ```json
  {"db": {"rules": [
     {"path": "votes", "read": "view", "write": "admin"},
     {"path": "votes/{self}", "write": "interact"},
     {"path": "meta", "read": "view", "write": "admin"}]},
   "user": {"scopes": ["profile"]},
   "comments": {"composer_only": true}}
  ```
- **People outside their organization** (clients, partners, friends): `mode` is `public` and set `owner` (e.g. "Sam").
  Publish with `capabilities: {"comments": {"composer_only": true}}` (no db, so it can be shared outside the org;
  this comments form keeps it shareable). Each person presses "Copy my choices" and sends the text back, or leaves
  comments, and you tally the pasted replies.

`comments` (composer-only) puts a **Comment on A** link under every option and section. It opens claude.ai's own
comment box pinned to that card, so remarks like "B, but with the strip from C" attach to the option they're about.
The page never writes comments itself and nobody is asked for consent.

**Publish in two passes, so the page carries its own invite.** Publish once to get the URL. Rebuild with
`--invite-url <that URL>`. Publish the same file path again: the URL stays the same, and leaving `capabilities` out
keeps them. The owner (and anyone who can edit) now sees an **Invite your people** panel with a one-click "Copy
invite message". Voters don't see it. The builder also prints the message.

**Check saving once** (team or solo only): ArtifactData `set` `votes/probe` with a small body, then `list` `votes`,
then `delete` it, pinning the version you got. The page ignores a doc called `probe`.

**Hand the user the share kit** in a few lines:
1. The link.
2. The one step only they can do: **open the page's Share menu and add the people** (or the whole organization; for
   `public`, turn on link sharing). Claude can't change sharing, so say this plainly.
3. The invite message, ready to paste into Slack or Teams.
4. An offer to deliver it in their channels. Every route goes outward, so show them the exact message first and send
   only after they say "send":
   - **Slack:** if a Slack connector with a send-message tool is available (ToolSearch "slack"), use it.
     Otherwise use the webhook script:
     `python3 "$SKILL_DIR/scripts/post_slack.py" post <channel> --title "<title>" --url <link> [--deadline …] [--from <name>]`.
     It's a dry run that prints the post. Add `--yes` only after approval. `post_slack.py channels` lists the
     channels set up. If none are, tell the user the one-time setup: in Slack, *Apps → Incoming Webhooks → Add to a
     channel*, copy the URL, then run `post_slack.py setup <channel> <url>`. The URL is stored privately in
     `~/.config/choices/`, never in the repo. Never print or echo a webhook URL.
   - **Email or chat** to named people: drafts only, with whatever the user has (an email or messaging skill or
     connector, or text to paste).
5. If there's a deadline, an offer to schedule a nudge (a reminder skill or a scheduled task, if available) for people the day before, and to close voting and
   tally at the deadline.

## 6. Read the picks

When the user says the picks are in (or asks for a status):
1. ArtifactData `list` on `votes` with `out_dir` set to a scratch folder.
2. `python3 "$SKILL_DIR/scripts/tally.py" <out_dir> choices.json [section-*.json ...]` prints the winners, counts
   or rank points, each voter's picks, and notes.
3. For team votes, resolve voter ids to names with ArtifactData `profiles`, and never write ids into documents
   people read.
4. **Read the comments:** ArtifactComments `read` with the page URL. Each thread is pinned to an option card or a
   section header. Map it by the anchored card's letter and name, or the section title. Fold the comments into the
   record next to the notes. They're often where the real reasoning ("A, but…") lives. Once the decision is
   recorded, reply briefly in threads that are activated for Claude ("Decided: B with C's strip, see the decision
   record") and resolve them. Leave threads that aren't activated alone, and tell the user they're still open.
5. To close voting (e.g. at the deadline), use ArtifactData `set` `meta/state` = `{"closed": true}`. The page locks
   and shows the final tallies.

Read notes carefully. "A but with C's header", "none of these" and "all of them" are real instructions. Interpret
them, and flag your reading in the record rather than guessing silently.

## 7. Record and hand off

Write a decision record from `references/decision-record.md`:
- in a git repo: `docs/decisions/NNNN-<slug>.md`, with the next number
- otherwise ask once where it should live (Notion, a wiki or notes tool the user has, or a plain file)

Include the picker link, what was chosen, the vote or tally, the notes, the consequences and the next steps. If
someone builds from it (an engineer, an agent, a designer), also write the build spec: the chosen option made
concrete, with its constraints. A decision only helps once someone can act on it.

## 8. Optional: refine round

If the winner is close but not settled, run round 2: 3 variations of the winner along the axis the notes complain
about (e.g. "denser", "warmer copy", "fewer services"), as a new section on the same page or a new page. Usually one
refine round is enough. Two at most.

## Pitfalls

- Options inside a card can't be interactive (no links, buttons or scripts). The builder rejects them because the
  whole card is the click target.
- SVG ids are auto-prefixed per option, so reusing ids like `grad1` across options is fine.
- Don't stack the deck: if one option is obviously best, the question wasn't worth asking. Sharpen the axis.
- Keep pages focused: about 6 sections and 20 questions is plenty for one sitting. Split bigger efforts into rounds.
- Never invent data inside options (fake metrics, fake quotes). Use placeholders like [PRICE].
