// Grain: one row per employee per month per triggered review RULE (transparent rules, not predictions).
let
    T = fnLoadCsv("FactReviewFlag.csv", {
        {"EmployeeKey", Int64.Type}, {"PeriodDateKey", Int64.Type}, {"Period", type text}, {"RuleCode", type text},
        {"RuleDescription", type text}, {"Evidence", type text}, {"Method", type text}})
in
    T
