"""EV-1: point-in-time S&P 500 membership into index_membership (ADR 0025).

Reconstructs membership INTERVALS from two public Wikipedia tables:
- the current-constituents table (symbol + its "Date added") on
  "List of S&P 500 companies";
- the changes table (effective date, added, removed) on
  "Historical components of the S&P 500" — comprehensive for roughly the last
  15 years, selected changes back to 1976 (the ADR records the limits).

Sweep per symbol, events in date order: an add opens an interval, a removal
closes the open one (opened at the 1900-01-01 FLOOR when the add predates the
records). Current members keep one open interval (removed NULL), seeded from
the constituents table's own "Date added" when the changes table has no
unclosed add. A non-current symbol whose last event is an add is a source gap:
WARNed and the dangling interval dropped (never written as "still a member").

Idempotent full rebuild each run: one transaction replaces the loader's own
(universe='SP500', source='wikipedia') slice. Monthly CronJob (toolkit image,
see cronjobs.yaml); job_runs bookkeeping via mdjob (AR-3).

Validation: the reconstructed current set is compared with active SP500 rows
in universe_constituents — drift > 10 symbols exits 1 (feed or parse broke).

Env: PGHOST, PGUSER, PGPASSWORD, PGDATABASE.
"""

import re
import sys
from datetime import date, datetime, timedelta

import requests
from lxml import html

from mdjob import connect, job_run

UA = {"User-Agent": "market-data-pipeline/1.0 (homelab research)"}
WIKI = "https://en.wikipedia.org/wiki/"
CURRENT_PAGE = WIKI + "List_of_S%26P_500_companies"
CHANGES_PAGE = WIKI + "Historical_components_of_the_S%26P_500"
FLOOR = date(1900, 1, 1)   # "before the records" sentinel
ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


def norm(ticker):
    """Wikipedia class shares (BRK.B) -> the universe's Yahoo form (BRK-B)."""
    return ticker.strip().upper().replace(".", "-")


def parse_changes_date(text):
    return datetime.strptime(text.strip(), "%B %d, %Y").date()


def current_members(tree):
    """{symbol: date_added_or_FLOOR} from the constituents table."""
    (table,) = tree.xpath('//table[@id="constituents"]')
    head = [th.text_content().strip() for th in table.xpath(".//tr[1]/th")]
    sym_i, added_i = head.index("Symbol"), head.index("Date added")
    out = {}
    for tr in table.xpath(".//tr")[1:]:
        cells = [c.text_content().strip() for c in tr.xpath("./td")]
        if len(cells) <= max(sym_i, added_i) or not cells[sym_i]:
            continue
        m = ISO.search(cells[added_i])
        out[norm(cells[sym_i])] = date.fromisoformat(m.group(0)) if m else FLOOR
    return out


def change_events(tree):
    """[(date, 'add'|'remove', symbol)] from the changes table (no rowspans:
    every row repeats its date; layout: date, add tkr, add name, rm tkr, rm name, …)."""
    (table,) = tree.xpath('//table[@id="changes"]')
    events = []
    for tr in table.xpath(".//tr"):
        cells = [c.text_content().strip() for c in tr.xpath("./td")]
        if len(cells) < 5:
            continue  # header rows
        try:
            d = parse_changes_date(cells[0])
        except ValueError:
            continue
        if cells[1]:
            events.append((d, "add", norm(cells[1])))
        if cells[3]:
            events.append((d, "remove", norm(cells[3])))
    return events


def build_intervals(current, events):
    """[(symbol, added, removed_or_None)]; see module docstring for the sweep."""
    by_symbol = {}
    for d, kind, sym in events:
        by_symbol.setdefault(sym, []).append((d, kind))
    intervals, dangling = [], []
    for sym in sorted(set(by_symbol) | set(current)):
        open_since, last_close = None, None
        for d, kind in sorted(by_symbol.get(sym, [])):
            if kind == "add":
                if open_since is None:
                    open_since = d
            else:
                # Removal with no recorded add: the stint began before the
                # records (FLOOR), or — after an earlier recorded removal —
                # at an unrecorded re-add, pinned just after that removal so
                # two FLOOR starts can never collide on the primary key.
                start = open_since or (last_close + timedelta(days=1)
                                       if last_close else FLOOR)
                intervals.append((sym, min(start, d), d))
                open_since, last_close = None, d
        if sym in current:
            start = open_since or current[sym]
            if last_close and start <= last_close:
                start = last_close + timedelta(days=1)
            intervals.append((sym, start, None))
        elif open_since is not None:
            dangling.append(sym)  # add without removal, yet not current: source gap
    return intervals, dangling


def main() -> int:
    with job_run("membership-history") as run:
        cur_tree = html.fromstring(requests.get(CURRENT_PAGE, headers=UA, timeout=120).content)
        chg_tree = html.fromstring(requests.get(CHANGES_PAGE, headers=UA, timeout=120).content)
        current = current_members(cur_tree)
        events = change_events(chg_tree)
        intervals, dangling = build_intervals(current, events)
        print(f"current={len(current)} events={len(events)} intervals={len(intervals)}",
              flush=True)
        for sym in dangling:
            print(f"WARN {sym}: add without removal and not current — interval dropped",
                  flush=True)
        if len(current) < 400 or len(events) < 300:
            print("ERROR: source tables implausibly small — refusing to replace data",
                  flush=True)
            return 1

        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT symbol FROM universe_constituents "
                            "WHERE universe='SP500' AND active")
                active = {r[0] for r in cur.fetchall()}
            drift = len(active ^ set(current))
            print(f"universe_constituents drift: {drift} symbol(s)", flush=True)
            if drift > 10:
                print("ERROR: reconstruction disagrees with universe_constituents "
                      "by more than 10 symbols", flush=True)
                return 1
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM index_membership "
                                "WHERE universe='SP500' AND source='wikipedia'")
                    cur.executemany(
                        "INSERT INTO index_membership "
                        "(universe, symbol, added, removed, source) "
                        "VALUES ('SP500', %s, %s, %s, 'wikipedia') "
                        "ON CONFLICT (universe, symbol, added) DO UPDATE "
                        "SET removed = EXCLUDED.removed",
                        intervals,
                    )
            run.rows = len(intervals)
        finally:
            conn.close()
        print(f"MEMBERSHIP-OK wrote {run.rows} intervals "
              f"({sum(1 for _s, _a, r in intervals if r is None)} open)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
