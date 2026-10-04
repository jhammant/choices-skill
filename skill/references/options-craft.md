# Making options worth choosing between

The value of /choices comes from the options. Three near-identical versions waste the decider's time. Three that
differ along the dimension that actually matters make the decision obvious, or reveal what the real question is.

## Pick the axis first

Before drawing anything, name the trade-off the decision turns on, then spread the options along it:

| Decision | Typical axes |
|---|---|
| Visual or UI direction | familiar ↔ bold, dense ↔ airy, product-first ↔ story-first |
| Architecture | build ↔ buy, simple now ↔ flexible later, sync ↔ event-driven, one service ↔ several |
| Messaging and positioning | what we do ↔ why it matters, technical ↔ outcome, plain ↔ provocative |
| Naming | descriptive ↔ evocative ↔ invented |
| Pricing | per seat ↔ usage ↔ flat tiers, low entry ↔ value-capture |
| Roadmap | quick wins ↔ big bets (use `rank` mode) |

A good default trio is **current (or closest to today) · a confident improvement · a bold option**. The decider then
sees the size of the change they'd be choosing as well as its direction.

## Rules that keep the choice honest

- **Same fidelity and format.** If one option gets a polished mock and another a sketch, the polish wins, not the
  idea. Matching size, detail and length also lets the decider compare the differences directly.
- **No strawmen.** Every option should be one you could defend. If you can't, replace it.
- **Name the trade-off.** 1–3 pros and cons each, specific ("adds a queue to operate"), never generic ("more
  complex").
- **Mark `current`** whenever there is an existing approach. The default is a real option, and choosing it is
  cheap.
- **Make option names memorable** in 2–5 words ("Code-first", "Story-led", "Event bus"), so a vote reads like a
  decision.
- **Two to four options.** Three is the sweet spot. Use four only when the axis really has four stops.
- **Real content, no lorem.** Use real copy, real service names and real constraints. Where a fact is unknown, use a
  bracket placeholder ([PRICE]) rather than inventing it.
- **Separate questions.** "Layout" and "colour" are two groups, not nine combinations. People mix and match in
  the notes.

## Content tips

- **Diagrams:** Mermaid `flowchart LR` for architecture, kept to 6–10 nodes. Pros and cons carry the operational
  cost.
- **Copy:** make every option the same length and register, so you're comparing the idea, not the word count.
- **UI mocks:** use a 320×200 or 400×260 viewBox, grey boxes for content and real copy only where it's the point.
- **Rank lists:** 5–10 items with a one-line blurb each, in `rank` mode. Use `many` mode for "which of these should
  we keep at all".
