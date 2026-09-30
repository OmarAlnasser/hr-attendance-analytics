let
    T = fnLoadCsv("DimShift.csv", {
        {"ShiftKey", Int64.Type}, {"ShiftCode", type text}, {"ShiftName", type text}, {"StartTime", type text},
        {"EndTime", type text}, {"GraceMinutes", Int64.Type}, {"CrossesMidnight", Int64.Type}, {"Workdays", type text}})
in
    T
