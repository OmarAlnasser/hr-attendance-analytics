"""Experimental early-warning model — FOR HUMAN REVIEW ONLY.

Target        P( weighted score in month t+1 < threshold ), predicted after month t closes.
Features      only information known at the end of month t (attendance of month t,
              evaluations of months <= t). Lags are calendar-aligned, so a missing
              month produces a missing value, never a silently shifted one.
Excluded      protected / sensitive attributes and identifiers (see FORBIDDEN).
Split         temporal: the last N target months form the test set; every training
              label is known before the first test prediction is made.
Baseline      persistence: flag if this month's score is already below threshold.
Limits        On synthetic data the model can only rediscover the rules written into
              the generator. Metrics say nothing about real employees. Correlation
              is not causation; the output must never trigger automatic action.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, confusion_matrix, f1_score, precision_score,
                             recall_score, roc_auc_score)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ..db import repos
from ..db.connection import now_str, read_sql, transaction
from ..domain.scoring import shift_period

FEATURES = [
    "weighted_score", "score_punctuality", "score_communication", "score_task_completion", "score_teamwork",
    "score_delta_1m", "score_mean_3m", "attendance_rate", "absence_rate", "late_rate", "incomplete_rate",
    "avg_late_minutes", "late_rate_delta_1m",
]
FORBIDDEN = {"gender", "sex", "nationality", "age", "birth_date", "religion", "marital_status", "ethnicity",
             "disability", "employee_id", "employee_code", "full_name", "department_id", "department_name"}
MIN_TRAIN_ROWS, MIN_TRAIN_POS, MIN_TEST_POS, MIN_TRAIN_PERIODS = 200, 30, 10, 3


@dataclass
class EvaluationReport:
    status: str                                   # 'model' | 'insufficient_data'
    threshold: float
    model_version: str
    created_at: str
    train_periods: list = field(default_factory=list)
    test_periods: list = field(default_factory=list)
    n_train: int = 0
    n_test: int = 0
    train_positive_rate: float | None = None
    test_positive_rate: float | None = None
    model_metrics: dict = field(default_factory=dict)
    baseline_metrics: dict = field(default_factory=dict)
    coefficients: dict = field(default_factory=dict)
    beats_baseline: bool | None = None
    reason: str = ""


def monthly_panel(conn) -> pd.DataFrame:
    att = read_sql("SELECT employee_id, substr(shift_date, 1, 7) AS period, status, is_late, late_minutes "
                            "FROM attendance_daily", conn)
    att["expected"] = att.status.isin(["present", "incomplete", "absent"]).astype(int)
    att["attended"] = att.status.isin(["present", "incomplete"]).astype(int)
    att["absent"] = (att.status == "absent").astype(int)
    att["incomplete"] = (att.status == "incomplete").astype(int)
    att["late"] = ((att.is_late == 1) & (att.attended == 1)).astype(int)
    att["late_min"] = np.where(att["late"] == 1, att["late_minutes"], 0)
    agg = att.groupby(["employee_id", "period"])[["expected", "attended", "absent", "incomplete", "late", "late_min"]].sum()
    agg = agg.reset_index()
    with np.errstate(divide="ignore", invalid="ignore"):
        agg["attendance_rate"] = np.where(agg.expected > 0, agg.attended / agg.expected, np.nan)
        agg["absence_rate"] = np.where(agg.expected > 0, agg.absent / agg.expected, np.nan)
        agg["late_rate"] = np.where(agg.attended > 0, agg.late / agg.attended, np.nan)
        agg["incomplete_rate"] = np.where(agg.attended > 0, agg.incomplete / agg.attended, np.nan)
        agg["avg_late_minutes"] = np.where(agg.late > 0, agg.late_min / agg.late, 0.0)
    ev = read_sql("SELECT employee_id, period, weighted_score, score_punctuality, score_communication, "
                           "score_task_completion, score_teamwork FROM performance_evaluations", conn)
    if ev.empty:
        return pd.DataFrame()
    periods = sorted(set(ev.period) | set(agg.period))
    grid = pd.MultiIndex.from_product([sorted(ev.employee_id.unique()), periods],
                                      names=["employee_id", "period"]).to_frame(index=False)
    panel = grid.merge(ev, how="left", on=["employee_id", "period"]).merge(
        agg[["employee_id", "period", "attendance_rate", "absence_rate", "late_rate", "incomplete_rate",
             "avg_late_minutes"]], how="left", on=["employee_id", "period"])
    panel = panel.sort_values(["employee_id", "period"]).reset_index(drop=True)
    g = panel.groupby("employee_id")
    # calendar-aligned lags: the grid has every month, so shift(1) is exactly the previous month
    panel["score_delta_1m"] = panel["weighted_score"] - g["weighted_score"].shift(1)
    panel["score_mean_3m"] = g["weighted_score"].transform(lambda s: s.rolling(3, min_periods=1).mean())
    panel["late_rate_delta_1m"] = panel["late_rate"] - g["late_rate"].shift(1)
    panel["next_score"] = g["weighted_score"].shift(-1)          # label source only, never a feature
    panel["target_period"] = panel["period"].map(lambda p: shift_period(p, 1))
    return panel.rename(columns={"period": "feature_period"})


def build_dataset(panel: pd.DataFrame, threshold: float) -> pd.DataFrame:
    assert not (set(FEATURES) & FORBIDDEN), "sensitive attribute in feature list"
    assert "next_score" not in FEATURES
    ds = panel[panel["weighted_score"].notna()].copy()
    ds["label_known"] = ds["next_score"].notna()
    ds["target"] = (ds["next_score"] < threshold).astype(int)
    return ds


def _metrics(y_true, y_pred, y_prob=None) -> dict:
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()
    out = {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
        "support_positive": int(tp + fn), "support_negative": int(tn + fp), "n": int(len(y_true)),
    }
    if y_prob is not None and len(set(y_true)) == 2:
        out["roc_auc"] = float(roc_auc_score(y_true, y_prob))
        out["average_precision"] = float(average_precision_score(y_true, y_prob))
    return out


def train_and_evaluate(conn, *, threshold: float, models_dir: str, n_test_months: int = 3) -> EvaluationReport:
    version = f"risk-lr-{datetime.now():%Y%m%d%H%M%S}"
    report = EvaluationReport("insufficient_data", threshold, version, now_str())
    panel = monthly_panel(conn)
    if panel.empty:
        report.reason = "No evaluations in the database."
        return _save(report, None, models_dir, conn)
    ds = build_dataset(panel, threshold)
    labelled = ds[ds.label_known]
    target_periods = sorted(labelled.target_period.unique())
    if len(target_periods) < n_test_months + MIN_TRAIN_PERIODS:
        report.reason = f"Only {len(target_periods)} labelled target months; need {n_test_months + MIN_TRAIN_PERIODS}."
        return _save(report, None, models_dir, conn)

    test_periods = target_periods[-n_test_months:]
    train = labelled[labelled.target_period < test_periods[0]]
    test = labelled[labelled.target_period >= test_periods[0]]
    # leakage guard: every training label must be known before the first test prediction
    assert train.target_period.max() <= test.feature_period.min()
    report.train_periods = sorted(train.target_period.unique().tolist())
    report.test_periods = test_periods
    report.n_train, report.n_test = int(len(train)), int(len(test))
    report.train_positive_rate = float(train.target.mean())
    report.test_positive_rate = float(test.target.mean())

    if len(train) < MIN_TRAIN_ROWS or train.target.sum() < MIN_TRAIN_POS or test.target.sum() < MIN_TEST_POS:
        report.reason = (f"Too few examples (train={len(train)}, train positives={int(train.target.sum())}, "
                         f"test positives={int(test.target.sum())}). Use the review RULES instead.")
        return _save(report, None, models_dir, conn)

    model = Pipeline([
        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
        ("scale", StandardScaler()),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=2000, C=1.0)),
    ])
    model.fit(train[FEATURES], train.target)
    prob = model.predict_proba(test[FEATURES])[:, 1]
    pred = (prob >= 0.5).astype(int)
    baseline = (test["weighted_score"] < threshold).astype(int)
    report.model_metrics = _metrics(test.target, pred, prob)
    report.baseline_metrics = _metrics(test.target, baseline)
    report.beats_baseline = report.model_metrics["f1"] > report.baseline_metrics["f1"] + 0.02
    names = list(model.named_steps["impute"].get_feature_names_out(FEATURES))
    report.coefficients = dict(sorted(zip(names, map(float, model.named_steps["clf"].coef_[0])),
                                      key=lambda kv: -abs(kv[1])))
    report.status = "model"
    return _save(report, model, models_dir, conn)


def _save(report: EvaluationReport, model, models_dir: str, conn=None) -> EvaluationReport:
    out = Path(models_dir)
    out.mkdir(parents=True, exist_ok=True)
    if model is not None:
        joblib.dump({"model": model, "features": FEATURES, "version": report.model_version,
                     "threshold": report.threshold}, out / "risk_model.joblib")
    summary = json.dumps(asdict(report), indent=2)
    (out / "model_evaluation.json").write_text(summary, encoding="utf-8")
    (out / "model_evaluation_report.md").write_text(render_markdown(report), encoding="utf-8")
    if conn is not None:     # a copy in the database for hosts without a persistent disk
        with transaction(conn):
            repos.save_file(conn, "models/model_evaluation.json", summary.encode("utf-8"), "application/json")
    return report


def score_latest(conn, models_dir: str) -> dict:
    path = Path(models_dir) / "risk_model.joblib"
    if not path.exists():
        return {"scored": 0, "reason": "No trained model; review rules are used instead."}
    bundle = joblib.load(path)
    panel = monthly_panel(conn)
    ds = panel[panel.weighted_score.notna()]
    latest = ds.feature_period.max()
    cur = ds[ds.feature_period == latest]
    prob = bundle["model"].predict_proba(cur[bundle["features"]])[:, 1]
    target = shift_period(latest, 1)
    rows = [(int(e), latest, target, float(p), "model", bundle["version"], now_str())
            for e, p in zip(cur.employee_id, prob)]
    with transaction(conn):
        repos.replace_risk_scores(conn, target, bundle["version"], rows)
    return {"scored": len(rows), "feature_period": latest, "target_period": target, "version": bundle["version"]}


def render_markdown(r: EvaluationReport) -> str:
    lines = [
        "# Experimental risk model — evaluation report",
        "",
        "> **SYNTHETIC DATA.** These numbers describe how well a model recovers patterns that were written "
        "into the data generator. They are not evidence about any real workforce. Output is for human review "
        "only and must never trigger automatic or disciplinary action.",
        "",
        f"* Status: **{r.status}**",
        f"* Model version: `{r.model_version}` — created {r.created_at}",
        f"* Target: next-month weighted score < **{r.threshold}**",
    ]
    if r.status != "model":
        lines += ["", f"**No model was accepted.** {r.reason}", "",
                  "The review page shows transparent rules instead; they are labelled as rules, not predictions."]
        return "\n".join(lines) + "\n"
    lines += [
        f"* Temporal split — train targets: {r.train_periods[0]} … {r.train_periods[-1]} "
        f"({r.n_train} rows, {r.train_positive_rate:.1%} positive); test targets: {', '.join(r.test_periods)} "
        f"({r.n_test} rows, {r.test_positive_rate:.1%} positive)",
        "",
        "| Metric (test set, decision threshold 0.5) | Model (logistic regression) | Baseline (persistence) |",
        "|---|---|---|",
    ]
    for k in ("precision", "recall", "f1"):
        lines.append(f"| {k.capitalize()} | {r.model_metrics[k]:.3f} | {r.baseline_metrics[k]:.3f} |")
    lines.append(f"| ROC AUC | {r.model_metrics.get('roc_auc', float('nan')):.3f} | n/a (binary rule) |")
    lines.append(f"| Average precision | {r.model_metrics.get('average_precision', float('nan')):.3f} | n/a |")
    for name, m in (("Model", r.model_metrics), ("Baseline", r.baseline_metrics)):
        cm = m["confusion_matrix"]
        lines += ["", f"**Confusion matrix — {name}** (n = {m['n']})", "",
                  "| | Predicted no | Predicted yes |", "|---|---|---|",
                  f"| Actual no | {cm['tn']} | {cm['fp']} |", f"| Actual yes | {cm['fn']} | {cm['tp']} |"]
    verdict = ("The model's F1 is more than 0.02 above the baseline on this test set."
               if r.beats_baseline else
               "The model does not clearly beat the simple baseline; prefer the baseline or the rules.")
    lines += ["", f"**Comparison:** {verdict}", "",
              "## Standardised coefficients (associations, not causes)", "",
              "| Feature | Coefficient |", "|---|---|"]
    lines += [f"| {k} | {v:+.3f} |" for k, v in list(r.coefficients.items())[:12]]
    lines += ["", "## Limitations", "",
              "* Synthetic data: the generator links punctuality, absence and scores by design, so good metrics are expected and prove nothing.",
              "* Small test window (3 months); metrics would vary with another seed.",
              "* Features exclude protected attributes and department; proxies can still exist and must be audited on real data.",
              "* Evaluations are subjective ratings; the model inherits any rater bias.",
              "* Use: prioritise supportive conversations. Never automatic or punitive decisions."]
    return "\n".join(lines) + "\n"
