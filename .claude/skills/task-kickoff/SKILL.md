---
name: task-kickoff
description: "Run once when the task brief arrives. Records the brief, maps the given material, gets one architecture pass and one grilling round, writes the decisions, then stops before any code. Pass `fable` to use architect-fable."
argument-hint: "[fable]"
disable-model-invocation: true
---

# Task kickoff

Frame and Model phases only. Budget: 25 of the 120 minutes (Frame 10, Model 15). Write no product code here.

Arguments: `$ARGUMENTS`. Use `architect-fable` only if the arguments contain `fable`;
otherwise `architect-opus`. In Codex use `architect-astra`.

## Steps

1. **Record.** Paste the brief verbatim into `docs/TASK.md` (Received, Brief, Test material). Log the
   start in `docs/AI_LOG.md`. Write the real user task and the baseline (current `risk-ledger proof`)
   under "My reading" before anything else: that is what good means.
2. **Map.** Spawn `researcher` on the given material only. It returns at most 15 lines: files, sizes,
   columns or bands, CRS, nodata value, spatial extent, time period, IDs, and anything surprising.
   If they gave a repo: its layout, how to run it, how to test it. End with which lines of
   "Assumed context" in `AGENTS.md` the material confirms or contradicts, and the unknowns that would
   change the design if they turned out differently.
3. **Place it.** Pick the closest row in the matrix below and state the plan delta in one line.
4. **Architect.** Spawn the architect with `docs/TASK.md`, `docs/GLOSSARY.md`, `docs/DECISIONS.md` and
   the map. Ask for at most 30 lines:
   - terms to add or rename, with the metric and its unit as field names
   - the Status set the data can actually produce
   - modules touched, and what to delete from the starter
   - verifiable units in order, each with the command that proves it and a budget in minutes
   - what to leave out, and why
   It assumes D4 to D9 and flags a deviation only with one concrete reason.
5. **Grill.** One round of the `grilling` skill on the open decisions: at most 5 questions, each with
   a recommended answer. Ten minutes at most.
6. **Write.** The lead writes `docs/GLOSSARY.md`, new `docs/DECISIONS.md` entries, the rest of "My reading" in
   `docs/TASK.md`, and planned rows in the README feature map, the user task first. Log verdicts in `docs/AI_LOG.md`.
7. **Stop.** Report the unit list. Building starts with the `verify` skill, one unit at a time.

## Feasibility matrix

| # | Task shape | Fit | Plan delta |
|---|---|---|---|
| 1 | API over precomputed results | full | rename `value` to the metric; swap the source adapter |
| 2 | Zonal statistics, raster by fields | high | rasterio or rioxarray adapter; drop the API if not asked |
| 3 | Point flood lookup per address | high | `out_of_coverage` becomes real; terms return period, `depth_m` |
| 4 | Notebook to reliable job | high | delete `api.py`; idempotent upsert keyed by inputs |
| 5 | Portfolio aggregation | high | count Assets without a value; never average them in as zero |
| 6 | Change in their existing repo | partial | copy `AGENTS.md`, agents and skills only; follow their layout |
| 7 | Small React view | high | `web/` is ready: Next 16.3.8 page over the API with an Effect client; adapt the Schema and view, about 20 minutes. Delete `web/` if no UI is asked |
| 8 | PostGIS query or schema | medium | `postgis/postgis:17-3.5` is pulled; fall back to DuckDB or GeoParquet |
| 9 | ML yield prediction or evaluation | medium | scikit-learn is cached; Prediction and Ground truth are new terms, not an Assessment |
| 10 | Docker, CI or deploy | medium | Docker locally; no cloud credentials, so write the deploy plan |
| 11 | STAC or Sentinel ingest | medium | pystac-client is cached; keep the area and period small |
| 12 | Rust core | low | no toolchain installed; say so and do it in Python |
