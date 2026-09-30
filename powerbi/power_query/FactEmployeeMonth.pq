// Grain: one row per employee per month in which they were employed (denominator for evaluation coverage).
let
    T = fnLoadCsv("FactEmployeeMonth.csv", {
        {"EmployeeKey", Int64.Type}, {"PeriodDateKey", Int64.Type}, {"Period", type text},
        {"DaysEmployed", Int64.Type}, {"IsEvaluable", Int64.Type}})
in
    T
