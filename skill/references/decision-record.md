# Decision record template

Use this shape (it's ADR-style and readable by people and agents). Keep it to one screen where possible. Link the
picker instead of copying its art.

```markdown
# NNNN. <Decision title>

- **Date:** YYYY-MM-DD
- **Decided by:** <names> (<solo | team vote, N voters>)
- **Picker:** <artifact link>
- **Status:** Decided | Superseded by NNNN

## Context
<2–4 sentences: what prompted the decision, the constraints, what existed before.>

## Options considered
| | Option | In one line | Main trade-off |
|---|---|---|---|
| A | <name> (current) | <blurb> | <pro / con> |
| B | <name> | … | … |
| C | <name> | … | … |

## Decision
**<Chosen option(s)>**, plus any mix-and-match from the notes, stated precisely.
<For team votes: the tally (e.g. "B 4 votes, A 2, C 1") and any strong dissent from the notes.>

## Notes and comments
- <name> (note on <section>): "<note>" → <how it's reflected, or "interpreted as …: confirm">
- <name> (comment on option <X>): "<comment>" → <how it's reflected>

## Consequences
- <What changes, what we now must do, what we gave up, risks to watch.>

## Next steps
- [ ] <owner>: <action> (<date>)
- Build spec: <link or section below>
```

## Build spec (when someone builds from the decision)

Add a section, or a separate file next to the record, that makes the chosen option concrete for whoever builds it:
exact copy, measurements, components or services, configuration, acceptance criteria, and what is explicitly out of
scope. For an agent hand-off, write it so the agent can start without reading the conversation.
