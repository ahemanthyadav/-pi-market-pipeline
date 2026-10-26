"""Monthly factor returns into factor_returns (G-20, 2026-10-26).

Two libraries, values stored in percent AS PUBLISHED (freq 'M', ts = month end):
- US  (source 'kenfrench'): Fama/French 5 Factors (2x3) + Momentum from the
  Ken French Data Library (Dartmouth Tuck). Factors MKT_RF SMB HML RMW CMA RF
  + MOM. Attribution: (c) Eugene F. Fama and Kenneth R. French.
- IN  (source 'iima'): the IIM-Ahmedabad four-factor library
  (survivorship-bias-adjusted monthly series). As published: WML is momentum
  (stored as MOM), MF the market factor (stored as MKT_RF). Cite:
  Agarwalla, S. K., Jacob, J. and Varma, J. R. (2013), "Four factor model in
  Indian equities market", W.P. No. 2013-09-05, IIM Ahmedabad.
  The release filename moves with each data release, so the index page is
  scraped for the current Monthly_SurvivorshipBiasAdjusted.csv link.

First mdjob adopter (AR-2/AR-3): write_window + job_run; mdjob.py is copied
into the build context at image build time (no cross-dir import, ADR 0004).
Idempotent: DELETE+INSERT per (market, factor, freq, ts). Per-library failures
WARN; exit 1 only if zero rows were written in total.

Env: PGHOST, PGUSER, PGPASSWORD, PGDATABASE.
"""

import calendar
import io
import re
import sys
import zipfile
from datetime import date

import requests

from mdjob import connect, job_run, write_window

UA = {"User-Agent": "market-data-pipeline/1.0 (homelab research)"}

KF_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
KF_FILES = [
    ("F-F_Research_Data_5_Factors_2x3_CSV.zip",
     {"Mkt-RF": "MKT_RF", "SMB": "SMB", "HML": "HML",
      "RMW": "RMW", "CMA": "CMA", "RF": "RF"}),
    ("F-F_Momentum_Factor_CSV.zip", {"Mom": "MOM"}),
]

IIMA_PAGE = "https://faculty.iima.ac.in/~iffm/Indian-Fama-French-Momentum/"
IIMA_LINK = re.compile(r'DATA/[\w.-]+_Monthly_SurvivorshipBiasAdjusted\.csv')
IIMA_MAP = {"SMB": "SMB", "HML": "HML", "WML": "MOM", "MF": "MKT_RF", "RF": "RF"}


def month_end(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def parse_kf(text, factor_map):
    """Monthly rows of a Ken French CSV: from the header line to the first
    non-YYYYMM row (the annual section). Returns [(ts, factor, value)]."""
    out = []
    header = None
    for line in text.splitlines():
        cells = [c.strip() for c in line.split(",")]
        if header is None:
            if any(c in factor_map for c in cells):
                header = cells
            continue
        if not re.fullmatch(r"\d{6}", cells[0] or ""):
            if out:
                break  # annual section reached
            continue
        ts = month_end(int(cells[0][:4]), int(cells[0][4:6]))
        for col, val in zip(header[1:], cells[1:]):
            factor = factor_map.get(col)
            if factor is None or val in ("", "NA"):
                continue
            v = float(val)
            if v <= -99.0:  # library's missing-value sentinels (-99.99 / -999)
                continue
            out.append((ts, factor, v))
    return out


def us_rows():
    rows = []
    for fname, fmap in KF_FILES:
        r = requests.get(KF_BASE + fname, headers=UA, timeout=120)
        r.raise_for_status()
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        text = zf.read(zf.namelist()[0]).decode("latin-1")
        rows += [{"market": "US", "factor": f, "ts": ts, "freq": "M",
                  "value": v, "source": "kenfrench"} for ts, f, v in parse_kf(text, fmap)]
    return rows


def in_rows():
    page = requests.get(IIMA_PAGE, headers=UA, timeout=60)
    page.raise_for_status()
    m = IIMA_LINK.search(page.text)
    if not m:
        raise RuntimeError("IIMA page no longer links a Monthly_SurvivorshipBiasAdjusted.csv")
    r = requests.get(IIMA_PAGE + m.group(0), headers=UA, timeout=120)
    r.raise_for_status()
    lines = r.text.splitlines()
    header = [c.strip() for c in lines[0].split(",")]
    rows = []
    for line in lines[1:]:
        cells = [c.strip() for c in line.split(",")]
        if not re.fullmatch(r"\d{4}-\d{2}", cells[0] or ""):
            continue
        ts = month_end(int(cells[0][:4]), int(cells[0][5:7]))
        for col, val in zip(header[1:], cells[1:]):
            factor = IIMA_MAP.get(col)
            if factor is None or val in ("", "NA"):
                continue
            rows.append({"market": "IN", "factor": factor, "ts": ts, "freq": "M",
                         "value": float(val), "source": "iima"})
    return rows


def main() -> int:
    with job_run("factors-fetcher") as run:
        rows = []
        for name, fn in (("US kenfrench", us_rows), ("IN iima", in_rows)):
            try:
                got = fn()
                print(f"{name}: {len(got)} rows", flush=True)
                rows += got
            except Exception as exc:  # noqa: BLE001 - one library down must not kill the other
                print(f"WARN {name} failed: {exc}", flush=True)
        if not rows:
            print("ERROR: zero factor rows fetched", flush=True)
            return 1
        conn = connect()
        run.rows, conn = write_window(conn, "factor_returns",
                                      ["market", "factor", "freq", "ts"], rows)
        conn.close()  # always the RETURNED conn — a retry replaces it
        print(f"FACTORS-OK wrote {run.rows} rows into factor_returns", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
