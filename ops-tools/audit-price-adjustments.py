#!/usr/bin/env python3
"""DQ-1 audit/repair helper: find symbols whose stored history is on a different price scale than Yahoo's.

Yahoo's daily `Close` is split/spin-off adjusted retroactively; stock_prices only refreshes the last
5 days, so a corporate action AFTER a symbol's backfill leaves every older row on the old scale
(proved 2026-10-12 with CTVA: DB 77.74 vs Yahoo 11.66 for the same day, `Stock Splits = 6.66` on the
spin-off date). This compares DB vs Yahoo closes at a few anchor dates and lists the mismatches.

Read-only against the DB. Needs yfinance + pandas on the workstation. The DB is reached through a psql
command you supply in $PSQL_CMD (never put a password on a command line in a doc), e.g.

  # against a local restored copy
  PSQL_CMD='docker exec -i tsmig psql -U postgres -d postgres' python3 ops-tools/audit-price-adjustments.py audit
  # against the cluster (password from the Secret, set in the environment only)
  PSQL_CMD='kubectl -n market-data exec -i timescaledb-0 -- env PGPASSWORD='"$PW"' psql -U postgres -d postgres' \\
      python3 ops-tools/audit-price-adjustments.py audit

Subcommands:
  audit                      write out/price-audit-<date>.csv (symbol, anchor, db_close, yahoo_close, ratio) and print
                             the symbols off by more than --tol (default 3 %) at ANY anchor.
  emit-repair SYM [SYM ...]  print SQL that replaces each symbol's whole history with Yahoo's current series
                             (midnight UTC on the trade date — the DQ-4 convention). Review, then pipe to psql.
"""
import argparse
import csv
import datetime as dt
import os
import subprocess
import sys

ANCHORS = ["2025-06-02", "2019-01-02", "2010-01-04"]


def psql(sql):
    cmd = os.environ.get("PSQL_CMD")
    if not cmd:
        sys.exit("set PSQL_CMD (see the module docstring)")
    out = subprocess.run(cmd + " -v ON_ERROR_STOP=1 -At -F, -c " + _q(sql), shell=True, check=True,
                         capture_output=True, text=True)
    return out.stdout


def _q(s):
    return "'" + s.replace("'", "'\"'\"'") + "'"


def symbols():
    return [s for s in psql("SELECT DISTINCT symbol FROM stock_prices ORDER BY 1").split("\n") if s]


def db_closes(anchor):
    end = (dt.date.fromisoformat(anchor) + dt.timedelta(days=7)).isoformat()
    rows = psql("SELECT symbol, ts::date, close FROM stock_prices WHERE ts >= '%s' AND ts < '%s' "
                "ORDER BY symbol, ts" % (anchor, end))
    first = {}
    for line in rows.split("\n"):
        if not line:
            continue
        sym, day, close = line.split(",")
        first.setdefault(sym, {})[day] = float(close)
    return first


def yahoo_closes(syms, anchor, batch=50, pause=3.0):
    """Close per symbol/day from Yahoo in small batches; a rate-limited batch is retried with backoff
    (a silent empty frame would look like 'no mismatch'). Returns (closes, symbols_never_answered)."""
    import time
    import yfinance as yf
    end = (dt.date.fromisoformat(anchor) + dt.timedelta(days=7)).isoformat()
    out, unanswered = {}, []
    for i in range(0, len(syms), batch):
        chunk = syms[i:i + batch]
        for attempt in range(6):
            d = yf.download(chunk, start=anchor, end=end, auto_adjust=False, progress=False,
                            threads=True, group_by="column")
            c = d["Close"] if len(d) else None
            if c is not None and len(c.columns) and c.notna().any().any():
                break
            time.sleep(20 * (attempt + 1))
        else:
            unanswered += chunk
            continue
        for sym in c.columns:
            col = c[sym].dropna()
            if len(col):
                out[sym] = {str(ix.date()): float(v) for ix, v in col.items()}
        time.sleep(pause)
    return out, unanswered


def audit(tol):
    rows, bad = [], {}
    for anchor in ANCHORS:
        mine = db_closes(anchor)
        theirs, unanswered = yahoo_closes(sorted(mine), anchor)
        if unanswered:
            print('anchor %s: Yahoo never answered for %d symbols (rate limit?): %s' %
                  (anchor, len(unanswered), ' '.join(unanswered[:20])), file=sys.stderr)
        n_before = len(rows)
        for sym, days in mine.items():
            common = sorted(set(days) & set(theirs.get(sym, {})))
            if not common:
                continue
            d0 = common[0]
            ratio = days[d0] / theirs[sym][d0] if theirs[sym][d0] else float("nan")
            rows.append((sym, d0, days[d0], theirs[sym][d0], round(ratio, 4)))
            if abs(ratio - 1) > tol:
                bad.setdefault(sym, []).append((d0, round(ratio, 3)))
        print("anchor %s: DB has %d symbols, compared %d (rest have no Yahoo bar that week)" %
              (anchor, len(mine), len(rows) - n_before), file=sys.stderr)
    os.makedirs("out", exist_ok=True)
    path = "out/price-audit-%s.csv" % dt.date.today().isoformat()
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "day", "db_close", "yahoo_close", "ratio"])
        w.writerows(rows)
    print("wrote", path, "(%d comparisons)" % len(rows), file=sys.stderr)
    for sym, hits in sorted(bad.items()):
        print("MISMATCH", sym, hits)
    print("mismatching symbols: %d" % len(bad), file=sys.stderr)


def emit_repair(syms):
    import yfinance as yf
    print("-- generated %s by audit-price-adjustments.py emit-repair — review before running" %
          dt.datetime.utcnow().strftime("%F %T UTC"))
    for sym in syms:
        h = yf.Ticker(sym).history(period="max", auto_adjust=False)
        h = h.dropna(subset=["Close"])
        if h.empty:
            print("-- %s: no Yahoo data, skipped" % sym)
            continue
        print("BEGIN;")
        print("DELETE FROM stock_prices WHERE symbol = '%s';" % sym.replace("'", ""))
        batch = []

        def flush():
            if batch:
                print("INSERT INTO stock_prices (symbol, ts, open, high, low, close, volume) VALUES\n  " +
                      ",\n  ".join(batch) + ";")
                batch.clear()
        for ts, r in h.iterrows():
            day = "%04d-%02d-%02d 00:00:00+00" % (ts.year, ts.month, ts.day)
            vol = "NULL" if r["Volume"] != r["Volume"] else str(int(r["Volume"]))
            batch.append("('%s','%s',%r,%r,%r,%r,%s)" % (sym, day, float(r["Open"]), float(r["High"]),
                                                          float(r["Low"]), float(r["Close"]), vol))
            if len(batch) >= 500:
                flush()
        flush()
        print("-- %s: %d rows" % (sym, len(h)))
        print("COMMIT;")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("audit")
    a.add_argument("--tol", type=float, default=0.03)
    e = sub.add_parser("emit-repair")
    e.add_argument("symbols", nargs="+")
    args = ap.parse_args()
    if args.cmd == "audit":
        audit(args.tol)
    else:
        emit_repair(args.symbols)


if __name__ == "__main__":
    main()
