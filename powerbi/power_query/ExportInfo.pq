let
    T = fnLoadCsv("ExportInfo.csv", {
        {"ExportedAt", type datetime}, {"RuleVersion", type text}, {"IsSyntheticData", Int64.Type},
        {"LowScoreThreshold", type number}, {"Note", type text}})
in
    T
