"""Universe refresh (Phase B): S&P 500 (Wikipedia) + Nifty 500 (NiftyIndices CSV).

Upserts universe_constituents (security-master fields) + ticker_names; symbols
absent from a fresh list flip active=false (history retained). Canary via
UNIVERSE_LIMIT (per universe). Graceful degrade: if a source fetch fails but we
already have rows, WARN + exit 0 (stale beats empty); exit 1 only if a source
fails AND its table would stay empty.
"""
import csv
import io
import os
import sys

import lxml.html
import psycopg
import requests

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
# niftyindices.com now serves a JS HTML shell at the old CSV path (2026-10-04);
# the NSE archives endpoint is the working CSV source — and it carries Industry.
NIFTY_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
UA = {"User-Agent": "Mozilla/5.0 (homelab market-data pipeline)"}


def sp500(limit):
    """Parse the constituents table directly (lxml.html) — pd.read_html proved
    unreliable on this page's markup."""
    resp = requests.get(WIKI_URL, headers=UA, timeout=60)
    resp.raise_for_status()
    table = lxml.html.fromstring(resp.content).get_element_by_id("constituents")
    rows = []
    for tr in table.xpath(".//tbody/tr"):
        cells = [td.text_content().strip() for td in tr.xpath("./th|./td")]
        if len(cells) < 3 or not cells[0] or cells[0] == "Symbol":
            continue
        sym = cells[0].replace(".", "-", 1)  # BRK.B -> BRK-B (Yahoo convention)
        cik = cells[6] if len(cells) > 6 else ""
        rows.append(("SP500", sym, cells[1], cells[2], None, cik, "US", "USD"))
    return rows[:limit] if limit else rows


def nifty500(limit):
    resp = requests.get(NIFTY_URL, headers=UA, timeout=60)
    resp.raise_for_status()
    if "text/html" in resp.headers.get("content-type", "").lower():
        raise RuntimeError("nifty list returned HTML (block page?), not CSV")
    rdr = csv.DictReader(io.StringIO(resp.text))
    rows = []
    for r in rdr:
        sym = (r.get("Symbol") or "").strip()
        if not sym or (r.get("Series") or "").strip() != "EQ":
            continue
        rows.append(("NIFTY500", f"{sym}.NS", (r.get("Company Name") or sym).strip(),
                     (r.get("Industry") or "").strip() or None,
                     (r.get("ISIN Code") or "").strip() or None,
                     None, "NSE", "INR"))
    return rows[:limit] if limit else rows


def main() -> int:
    limit = int(os.environ.get("UNIVERSE_LIMIT", "0") or 0) or None
    conn = psycopg.connect(
        host=os.environ.get("PGHOST", "timescaledb.market-data.svc.cluster.local"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ["PGPASSWORD"],
        dbname=os.environ.get("PGDATABASE", "postgres"),
    )
    total = {}
    empty_after_fail = []
    with conn:
        with conn.cursor() as cur:
            for universe, fetcher in (("SP500", sp500), ("NIFTY500", nifty500)):
                try:
                    rows = fetcher(limit)
                except Exception as exc:  # noqa: BLE001
                    cur.execute("SELECT count(*) FROM universe_constituents WHERE universe=%s",
                                (universe,))
                    have = cur.fetchone()[0]
                    print(f"WARN {universe} fetch failed ({exc}); existing rows={have}",
                          flush=True)
                    if have == 0:
                        empty_after_fail.append(universe)
                    continue
                cur.execute("UPDATE universe_constituents SET active=false, last_seen=now() "
                            "WHERE universe=%s", (universe,))
                for (uni, sym, name, sector, isin, cik, exch, ccy) in rows:
                    cur.execute(
                        """INSERT INTO universe_constituents
                           (universe, symbol, name, sector, isin, cik, exchange, currency,
                            active, first_seen, last_seen)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s, TRUE, now(), now())
                           ON CONFLICT (universe, symbol) DO UPDATE SET
                             name=EXCLUDED.name, sector=EXCLUDED.sector,
                             isin=EXCLUDED.isin, cik=EXCLUDED.cik,
                             exchange=EXCLUDED.exchange, currency=EXCLUDED.currency,
                             active=TRUE, last_seen=now()""",
                        (uni, sym, name, sector, isin, cik, exch, ccy))
                    cur.execute(
                        "INSERT INTO ticker_names (ticker, name) VALUES (%s,%s) "
                        "ON CONFLICT (ticker) DO UPDATE SET name=EXCLUDED.name",
                        (sym, name))
                cur.execute("SELECT count(*) FROM universe_constituents "
                            "WHERE universe=%s AND active", (universe,))
                total[universe] = cur.fetchone()[0]
                print(f"{universe}: {len(rows)} fetched, {total[universe]} active", flush=True)
                if not limit:
                    # G-2a / EV-1: append-only weekly record of who was in the index, so
                    # future backtests are not limited to today's survivors. One row per
                    # (universe, date, symbol); a same-day re-run adds nothing.
                    cur.execute("INSERT INTO universe_membership_snapshots "
                                "(universe, snapshot_date, symbol, sector) "
                                "SELECT universe, current_date, symbol, sector "
                                "FROM universe_constituents WHERE universe=%s AND active "
                                "ON CONFLICT DO NOTHING", (universe,))
                    print(f"{universe}: snapshot {cur.rowcount} rows", flush=True)
    conn.close()
    if empty_after_fail:
        print(f"UNIVERSE-FAIL empty after fetch failure: {empty_after_fail}", flush=True)
        return 1
    if limit:
        print(f"UNIVERSE-CANARY-OK {total}", flush=True)
    else:
        ok = total.get("SP500", 0) >= 495 and total.get("NIFTY500", 0) >= 490
        print(f"UNIVERSE-OK active={total} {'PASS' if ok else 'WARN-LOW-COUNT'}", flush=True)
        return 0 if total.get("SP500", 0) and total.get("NIFTY500", 0) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
