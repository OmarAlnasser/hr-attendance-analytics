// Grain: one row per employee per target month. EXPERIMENTAL model output; may be empty when the model
// status is insufficient_data. For human review only.
let
    T = fnLoadCsv("FactRiskScore.csv", {
        {"EmployeeKey", Int64.Type}, {"TargetPeriodDateKey", Int64.Type}, {"FeaturePeriod", type text},
        {"TargetPeriod", type text}, {"Probability", type number}, {"Method", type text}, {"ModelVersion", type text}})
in
    T
