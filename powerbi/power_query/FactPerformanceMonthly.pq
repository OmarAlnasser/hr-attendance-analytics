// Grain: one row per employee per evaluated month. PeriodDateKey = first day of the month.
// Weight* columns are the weights snapshot used for that evaluation (they sum to 100).
let
    T = fnLoadCsv("FactPerformanceMonthly.csv", {
        {"EmployeeKey", Int64.Type}, {"PeriodDateKey", Int64.Type}, {"Period", type text},
        {"PunctualityScore", Int64.Type}, {"CommunicationScore", Int64.Type}, {"TaskCompletionScore", Int64.Type},
        {"TeamworkScore", Int64.Type}, {"WeightedScore", type number}, {"WeightPunctuality", type number},
        {"WeightCommunication", type number}, {"WeightTaskCompletion", type number}, {"WeightTeamwork", type number},
        {"EvaluatorUserKey", Int64.Type}})
in
    T
