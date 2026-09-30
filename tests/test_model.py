"""Experimental model: no leakage, temporal split, baseline comparison, fallback when data are insufficient."""
import json
import unittest
from datetime import datetime
from pathlib import Path

from hr_analytics.ml.risk_model import FEATURES, FORBIDDEN, build_dataset, monthly_panel, train_and_evaluate
from hr_analytics.pipeline.importer import import_punch_file
from hr_analytics.pipeline.processor import process_attendance, range_for_batch
from hr_analytics.services.seed import load_evaluations, load_master_data
from hr_analytics.synthetic.generator import generate

from .support import TempDirMixin


def load_synthetic(test, months: int, employees: int, start: str):
    data = test.tmp / "synthetic"
    generate(data, seed=11, start=start, months=months, n_employees=employees, n_new_hires=2)
    load_master_data(test.conn, data, settings=test.settings, demo_password="not-used-in-this-test",
                     first_period=start[:7])
    load_evaluations(test.conn, data)
    lo = hi = None
    for f in sorted((data / "punches").iterdir()):
        r = import_punch_file(test.conn, f, settings=test.settings, as_of=datetime(2030, 1, 1))
        rng = range_for_batch(r.min_punch_time, r.max_punch_time, test.conn, r.batch_id)
        lo = rng[0] if lo is None else min(lo, rng[0])
        hi = rng[1] if hi is None else max(hi, rng[1])
    process_attendance(test.conn, lo, hi, settings=test.settings, as_of=datetime(2030, 1, 1))


class InsufficientDataTests(TempDirMixin, unittest.TestCase):
    def test_small_history_falls_back_to_rules(self):
        load_synthetic(self, months=4, employees=20, start="2025-09-01")
        rep = train_and_evaluate(self.conn, threshold=3.0, models_dir=self.settings.MODELS_DIR)
        self.assertEqual(rep.status, "insufficient_data")
        self.assertTrue(rep.reason)
        saved = json.loads((Path(self.settings.MODELS_DIR) / "model_evaluation.json").read_text())
        self.assertEqual(saved["status"], "insufficient_data")
        self.assertFalse((Path(self.settings.MODELS_DIR) / "risk_model.joblib").exists())


class ModelTests(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        load_synthetic(self, months=10, employees=60, start="2025-09-01")

    def test_features_are_safe_and_known_before_the_target_month(self):
        self.assertFalse(set(FEATURES) & FORBIDDEN)
        self.assertNotIn("next_score", FEATURES)
        panel = monthly_panel(self.conn)
        ds = build_dataset(panel, 3.0)
        self.assertTrue((ds["feature_period"] < ds["target_period"]).all())
        # the label for row (employee, m) is the score of month m+1 for the same employee
        ev = {(r[0], r[1]): r[2] for r in self.conn.execute(
            "SELECT employee_id, period, weighted_score FROM performance_evaluations")}
        known = ds[ds.label_known].head(50)
        for r in known.itertuples():
            self.assertAlmostEqual(r.next_score, ev[(r.employee_id, r.target_period)])
            self.assertAlmostEqual(r.weighted_score, ev[(r.employee_id, r.feature_period)])

    def test_temporal_split_and_reported_metrics(self):
        rep = train_and_evaluate(self.conn, threshold=3.0, models_dir=self.settings.MODELS_DIR, n_test_months=3)
        if rep.status != "model":
            self.skipTest(f"generator produced too few positives for a model: {rep.reason}")
        self.assertLess(max(rep.train_periods), min(rep.test_periods))
        for m in (rep.model_metrics, rep.baseline_metrics):
            for key in ("precision", "recall", "f1", "confusion_matrix", "n"):
                self.assertIn(key, m)
            self.assertEqual(m["n"], rep.n_test)
            cm = m["confusion_matrix"]
            self.assertEqual(cm["tn"] + cm["fp"] + cm["fn"] + cm["tp"], rep.n_test)
        md = (Path(self.settings.MODELS_DIR) / "model_evaluation_report.md").read_text()
        self.assertIn("SYNTHETIC", md)
        self.assertIn("Baseline", md)


if __name__ == "__main__":
    unittest.main()
