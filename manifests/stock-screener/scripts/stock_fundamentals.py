"""Fundamentals ingestion (Phase E): statements + live ratios, max history.

Per symbol (resumable via job_state cursor):
- US (CIK present): SEC EDGAR companyfacts XBRL — official statement history
  (~2009→ structured). Metrics: revenue, net income, operating income, EPS,
  equity, long-term debt, OCF, capex → FCF. filing_published_at = EDGAR 'filed'.
- NSE (no CIK): yfinance annual statements — same metric names.
- All symbols: yfinance info live ratios (pe, pb, ev_ebitda, roe,
  operating_margin, market_cap) stamped ts=fetch date (last-write-wins).

Weekly cadence; BACKFILL=1 processes the whole universe from the cursor
(canary via CANARY_LIMIT). Point-in-time: yfinance legs carry
filing_published_at = fetch date (our DB could not know earlier).
SEC courtesy: declared User-Agent + 0.4s spacing (10 req/s policy).
"""
import json
import os
import sys
import time

import psycopg
import requests
import yfinance as yf

UA = {"User-Agent": "piCluster market-data pipeline contact: homelab-admin@localhost"}
EDGAR = "https://data.sec.gov/api/xbrl/companyfacts/CIK{}.json"

# EDGAR metric -> accepted us-gaap tags (first match wins)
EDGAR_MAP = {
    "total_revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
    "net_income": ["NetIncomeLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
    "shareholder_equity": ["StockholdersEquity"],
    "total_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
}
# yfinance statement row -> metric. yfinance 1.7 renamed rows to CamelCase
# (e.g. "NetIncome"); candidate lists cover both 0.2.x spaced names and 1.7+.
YF_MAP = {
    "total_revenue": ["Total Revenue", "TotalRevenue"],
    "net_income": ["Net Income", "NetIncome"],
    "operating_income": ["Operating Income", "OperatingIncome"],
    "eps": ["Diluted EPS", "DilutedEPS"],
    "shareholder_equity": ["Stockholders Equity", "StockholdersEquity"],
    "total_debt": ["Total Debt", "TotalDebt"],
    "fcf": ["Free Cash Flow", "FreeCashFlow"],
}
INFO_RATIOS = {
    "pe": "trailingPE", "pb": "priceToBook", "ev_ebitda": "enterpriseToEbitda",
    "roe": "returnOnEquity", "operating_margin": "operatingMargins",
    "market_cap": "marketCap",
}


def upsert(cur, symbol, ts, metric, value, source, published):
    if value is None:
        return 0
    cur.execute("DELETE FROM stock_fundamentals WHERE symbol=%s AND ts=%s "
                "AND metric=%s AND source=%s", (symbol, ts, metric, source))
    cur.execute("INSERT INTO stock_fundamentals "
                "(symbol, ts, metric, value, source, filing_published_at) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (symbol, ts, metric, float(value), source, published))
    return 1


def edgar_facts(cik, symbol, cur):
    """Ingest FULL EDGAR history: one row per (metric, period end) — the version
    with the latest 'filed' date wins (restatements supersede, v1 semantics).
    Annual + quarterly periods share end dates; 10-K supersedes 10-Q there
    (filed later). FCF derived as ocf − capex per matching period end."""
    r = requests.get(EDGAR.format(cik.zfill(10)), headers=UA, timeout=60)
    r.raise_for_status()
    facts = r.json().get("facts", {}).get("us-gaap", {})
    best = {}  # (metric, end) -> (val, filed)
    for metric, tags in EDGAR_MAP.items():
        for tag in tags:
            # companyfacts nesting: facts.{namespace}.{tag}.units.{unit}[]
            units = (facts.get(tag) or {}).get("units", {})
            for unit, entries in units.items():
                if unit not in ("USD", "USD/shares"):
                    continue
                for e in entries:
                    if e.get("form") not in ("10-K", "10-Q") or not e.get("end"):
                        continue
                    key = (metric, e["end"])
                    filed = e.get("filed", "")
                    if key not in best or filed > best[key][1]:
                        best[key] = (float(e["val"]), filed)
    rows = 0
    ends = {end for (_m, end) in best}
    for end in ends:
        ocf = best.get(("ocf", end))
        capex = best.get(("capex", end))
        if ocf and capex:
            best[("fcf", end)] = (ocf[0] - capex[0], max(ocf[1], capex[1]))
    for (metric, end), (val, filed) in best.items():
        if metric in ("ocf", "capex"):
            continue  # raw inputs kept out of the metric table (fcf derived)
        rows += upsert(cur, symbol, f"{end}T00:00:00Z", metric, val,
                       "edgar", f"{filed}T00:00:00Z" if filed else None)
    return rows


def yf_statements(symbol, cur, fetch_date):
    """Annual statements via yfinance, version-proof row lookup (0.2.x or 1.7+)."""
    tk = yf.Ticker(symbol)
    rows = 0
    frames = []
    try:
        for getter, attrs in (("get_income_stmt", ("income_stmt",)),
                               ("get_balance_sheet", ("balance_sheet",)),
                               ("get_cashflow", ("cash_flow", "cashflow"))):
            fn = getattr(tk, getter, None)
            if fn:
                frames.append(fn(freq="yearly"))
            else:
                frames.append(next((getattr(tk, a) for a in attrs
                                    if getattr(tk, a, None) is not None), None))
    except Exception as exc:  # noqa: BLE001
        print(f"WARN {symbol} statements failed: {exc}", flush=True)
        return 0
    for metric, cands in YF_MAP.items():
        for frame in frames:
            if frame is None or not len(getattr(frame, "index", [])):
                continue
            hit = next((c for c in cands if c in frame.index), None)
            if hit is None:
                continue
            for col in frame.columns:
                v = frame.loc[hit, col]
                if v is not None and v == v:
                    rows += upsert(cur, symbol, col, metric, v, "yfinance", fetch_date)
            break
    return rows


def yf_ratios(symbol, cur, fetch_date):
    try:
        info = yf.Ticker(symbol).info or {}
    except Exception as exc:  # noqa: BLE001
        print(f"WARN {symbol} info failed: {exc}", flush=True)
        return 0
    rows = 0
    for metric, key in INFO_RATIOS.items():
        v = info.get(key)
        if isinstance(v, (int, float)):
            rows += upsert(cur, symbol, fetch_date, metric, v, "yfinance", fetch_date)
    return rows


def main() -> int:
    backfill = os.environ.get("BACKFILL", "1") == "1"
    limit = int(os.environ.get("CANARY_LIMIT", "0") or 0) or None
    job = "stock_fundamentals"
    conn = psycopg.connect(
        host=os.environ.get("PGHOST", "timescaledb.market-data.svc.cluster.local"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ["PGPASSWORD"],
        dbname=os.environ.get("PGDATABASE", "postgres"),
    )
    conn.autocommit = True  # reads idle-transaction-safe (lesson 2026-10-04)
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, coalesce(cik,'') FROM universe_constituents "
                    "WHERE active ORDER BY 1")
        universe = [(r[0], r[1]) for r in cur.fetchall()]
        if limit:
            universe = universe[:limit]
        if backfill:
            cur.execute("SELECT last_key FROM job_state WHERE job_name=%s", (job,))
            row = cur.fetchone()
            if row and row[0]:
                universe = [u for u in universe if u[0] > row[0]]
    if not universe:
        if backfill:
            # Empty post-cursor universe in backfill mode = the pass already
            # completed (a previous attempt died between the last symbol and
            # the clear). Clear so the next run starts fresh (2026-10-04 lesson).
            with conn.cursor() as cur:
                cur.execute("UPDATE job_state SET last_key=NULL WHERE job_name=%s",
                            (job,))
            print("pass already complete — cursor cleared", flush=True)
        else:
            print("nothing to do", flush=True)
        return 0
    print(f"symbols={len(universe)} (resumable)", flush=True)
    done, rows = 0, 0
    for symbol, cik in universe:
        fetch_date = f"{time.strftime('%Y-%m-%d')}T00:00:00Z"
        wrote = 0
        try:
            if cik:
                with conn.transaction():
                    with conn.cursor() as cur:
                        wrote += edgar_facts(cik, symbol, cur)
                time.sleep(0.4)
            with conn.transaction():
                with conn.cursor() as cur:
                    wrote += yf_statements(symbol, cur, fetch_date)
                    wrote += yf_ratios(symbol, cur, fetch_date)
        except psycopg.OperationalError as exc:
            print(f"WARN {symbol} conn dropped ({exc}); reconnecting", flush=True)
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            conn = psycopg.connect(
                host=os.environ.get("PGHOST", "timescaledb.market-data.svc.cluster.local"),
                user=os.environ.get("PGUSER", "postgres"),
                password=os.environ["PGPASSWORD"],
                dbname=os.environ.get("PGDATABASE", "postgres"),
            )
            conn.autocommit = True
        except Exception as exc:  # noqa: BLE001
            print(f"WARN {symbol} failed: {exc}", flush=True)
        else:
            done += 1
            rows += wrote
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO job_state (job_name, last_key, updated_at) "
                                "VALUES (%s,%s,now()) ON CONFLICT (job_name) DO UPDATE "
                                "SET last_key=EXCLUDED.last_key, updated_at=now()",
                                (job, symbol))
        time.sleep(1.2 if not cik else 0.3)
    if backfill and done + failed >= len(universe):
        with conn.cursor() as cur:
            cur.execute("UPDATE job_state SET last_key=NULL WHERE job_name=%s", (job,))
        print("cursor cleared (full pass complete)", flush=True)
    conn.close()
    print(f"FUNDAMENTALS-OK done={done}/{len(universe)} rows={rows}", flush=True)
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
