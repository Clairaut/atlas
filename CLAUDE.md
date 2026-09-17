# atlas

Ephemeris toolkit: a CLI (`atlas observe`, `compare`, `cast`) over pyswisseph,
plus a FastAPI server in `src/atlas/serve.py` that exposes the same three verbs
as `/observe`, `/compare` and `/cast`. Deployed to hades at `/srv/atlas`
(`sudo srv-deploy atlas`), published as `atlas.liminance.net`, and read by both
the `clairaut.atlas` bar widget and the `personal` MCP host.

Installed locally with `pipx install -e`. Config is `~/.config/atlas/atlas.toml`,
which is tracked in the dotfiles repo; ephemeris files live at the path it names
(`~/.local/share/atlas/ephe` here, `/srv/atlas/ephe` on hades). They are not in
`~/.ephe` any more.

## Language

**Astrology is not about birth.** Birth is one application of it, so nothing here
uses birth or natal framing: not in names, parameters, output strings or docs. A
chart is cast for a moment and a place, and one of those moments happens to be
someone's birth.

Follow from that:

- Functions are **verbs**: `observe`, `compare`, `cast`, `locate`. Not
  `aspects`, not nouns.
- No `_many` suffixes. One function takes many bodies: `for target in targets`,
  not a separate `locate_many`.
- Datetimes end in `_at` (`transit_at`), never a bare noun like `against`.
- Keep domain words general rather than pinned to one use. `build_transit_aspects`
  compares two charts; it is not limited to transits against a chart someone was
  born under, and a single chart compared with itself is a legitimate call.

## Server

The three routes are the tool surface the `personal` MCP host exposes, listed in
`~/.config/personal-mcp/apis.toml`. Renaming a route silently drops the
corresponding tool, since tools are generated from the live OpenAPI spec and
matched by path.
