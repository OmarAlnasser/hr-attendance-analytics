# Experimental risk model — evaluation report

> **SYNTHETIC DATA.** These numbers describe how well a model recovers patterns that were written into the data generator. They are not evidence about any real workforce. Output is for human review only and must never trigger automatic or disciplinary action.

* Status: **model**
* Model version: `risk-lr-20261001135715` — created 2026-10-01 13:57:15
* Target: next-month weighted score < **3.0**
* Temporal split — train targets: 2025-10 … 2026-05 (811 rows, 12.6% positive); test targets: 2026-06, 2026-07, 2026-08 (319 rows, 10.7% positive)

| Metric (test set, decision threshold 0.5) | Model (logistic regression) | Baseline (persistence) |
|---|---|---|
| Precision | 0.337 | 0.417 |
| Recall | 0.824 | 0.441 |
| F1 | 0.479 | 0.429 |
| ROC AUC | 0.896 | n/a (binary rule) |
| Average precision | 0.576 | n/a |

**Confusion matrix — Model** (n = 319)

| | Predicted no | Predicted yes |
|---|---|---|
| Actual no | 230 | 55 |
| Actual yes | 6 | 28 |

**Confusion matrix — Baseline** (n = 319)

| | Predicted no | Predicted yes |
|---|---|---|
| Actual no | 264 | 21 |
| Actual yes | 19 | 15 |

**Comparison:** The model's F1 is more than 0.02 above the baseline on this test set.

## Standardised coefficients (associations, not causes)

| Feature | Coefficient |
|---|---|
| score_mean_3m | -1.018 |
| score_punctuality | +0.685 |
| score_task_completion | -0.571 |
| score_communication | -0.495 |
| late_rate | +0.295 |
| weighted_score | -0.252 |
| score_teamwork | -0.224 |
| score_delta_1m | +0.168 |
| late_rate_delta_1m | +0.163 |
| avg_late_minutes | +0.149 |
| attendance_rate | -0.144 |
| absence_rate | +0.144 |

## Limitations

* Synthetic data: the generator links punctuality, absence and scores by design, so good metrics are expected and prove nothing.
* Small test window (3 months); metrics would vary with another seed.
* Features exclude protected attributes and department; proxies can still exist and must be audited on real data.
* Evaluations are subjective ratings; the model inherits any rater bias.
* Use: prioritise supportive conversations. Never automatic or punitive decisions.
