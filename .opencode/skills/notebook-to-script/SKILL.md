---
name: Notebook to Script
description: Use when converting exploratory notebook code into a tested, runnable module or pipeline job — cell inventory, function extraction, config at the top, I/O at the edges, tests for the tricky parts.
---

# Notebook → script

1. **Inventory the notebook.** List every cell; mark KEEP (feeds the final
   output), KEEP-AS-TEST (surfaced an edge case), DEAD (explored, rejected).
   Delete DEAD cells without ceremony — the repo is not the lab notebook.
2. **Extract pure functions.** Each KEEP cell becomes a function named for what
   it computes; inputs and outputs explicit; no cell-level globals. Display
   calls (`print`, `.head()`, plots) move behind an optional `--report` flag
   or die.
3. **Config at the top** (or argparse CLI): file paths, tickers, date ranges,
   thresholds — everything that was hard-coded mid-notebook. No magic numbers
   below the config block.
4. **I/O at the edges.** Read once at start, write once at end; functions in
   between are pure. State the data contract: input grain, output grain.
5. **Test the tricky parts.** The cells that had surprises (odd dtypes,
   timezone traps, empty edge cases) become pytest cases with the notebook's
   actual shapes as fixtures. Run `pytest` before calling it done.
6. **For pipeline jobs:** structure as fetch → transform → load with the
   idempotent DELETE+INSERT pattern (`sql-conventions` skill), WARN-and-continue
   per item, and a final log line of the house form:
   `"wrote N rows into <table>"` — validation jobs match on it (manual §6).
