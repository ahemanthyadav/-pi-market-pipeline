#!/usr/bin/env python3
"""EV-0 harness tests on synthetic data: a planted signal must pass, noise must not.

    python3 tests/test_ev0.py
"""
import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

OPS = Path(__file__).resolve().parent.parent / "ops-tools"
spec = importlib.util.spec_from_file_location("ev0", OPS / "ev0.py")
ev0 = importlib.util.module_from_spec(spec)
sys.modules["ev0"] = ev0
spec.loader.exec_module(ev0)


def panel(seed, months=120, names=200, strength=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2005-01-31", periods=months, freq="ME")
    cols = [f"S{i}" for i in range(names)]
    sig = pd.DataFrame(rng.normal(size=(months, names)), idx, cols)
    fwd = pd.DataFrame(rng.normal(scale=0.08, size=(months, names)), idx, cols) + strength * 0.08 * sig
    liq = pd.DataFrame(1.0, idx, cols)
    return sig, fwd, liq


class Harness(unittest.TestCase):
    def test_planted_signal_passes_criteria_1_and_3(self):
        sig, fwd, liq = panel(1, strength=0.15)
        s = ev0.summarize(ev0.evaluate(sig, fwd, liq, {}, cost=0.002))
        self.assertGreater(s["ic_t_nw"], 3)
        self.assertGreater(s["net_ann"], 0)
        self.assertGreater(s["ic_h1"], 0)
        self.assertGreater(s["ic_h2"], 0)

    def test_noise_does_not_pass(self):
        sig, fwd, liq = panel(2, strength=0.0)
        s = ev0.summarize(ev0.evaluate(sig, fwd, liq, {}, cost=0.002))
        self.assertLess(abs(s["ic_t_nw"]), 3)
        verdict, _ = ev0.verdict({"SP500": s})
        self.assertEqual(verdict, "FAIL")

    def test_fama_macbeth_drops_a_signal_explained_by_a_control(self):
        sig, fwd, liq = panel(3, strength=0.15)
        rng = np.random.default_rng(9)
        clone = sig + pd.DataFrame(rng.normal(scale=0.05, size=sig.shape), sig.index, sig.columns)
        alone = ev0.summarize(ev0.evaluate(clone, fwd, liq, {}, 0.002))
        ctrl = ev0.summarize(ev0.evaluate(clone, fwd, liq, {"orig": sig}, 0.002))
        self.assertGreater(abs(alone["fm_t_nw"]), abs(ctrl["fm_t_nw"]))

    def test_turnover_is_zero_for_a_static_signal_and_costs_bite(self):
        sig, fwd, liq = panel(4, strength=0.15)
        static = pd.DataFrame(np.tile(sig.iloc[0].values, (len(sig), 1)), sig.index, sig.columns)
        m = ev0.evaluate(static, fwd, liq, {}, cost=0.01)
        self.assertEqual(m.turnover.iloc[1:].max(), 0.0)
        self.assertLess(m.net.iloc[0], m.spread.iloc[0])  # first month pays full entry

    def test_nw_t_matches_plain_t_for_iid_and_needs_data(self):
        x = np.random.default_rng(5).normal(0.1, 1, 2000)
        plain = x.mean() / (x.std(ddof=0) / np.sqrt(len(x)))
        self.assertAlmostEqual(ev0.nw_t(x, lag=0), plain, places=6)
        self.assertTrue(np.isnan(ev0.nw_t([1.0, 2.0])))

    def test_signals_skip_the_last_month_for_12_1(self):
        idx = pd.bdate_range("2020-01-01", periods=400)
        px = pd.DataFrame({"A": np.linspace(100, 200, 400)}, idx)
        s = ev0.signals(px, px * 0 + 1e6, px)
        self.assertAlmostEqual(s["ret_12_1"]["A"].iloc[-1], px.A.iloc[-22] / px.A.iloc[-253] - 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
