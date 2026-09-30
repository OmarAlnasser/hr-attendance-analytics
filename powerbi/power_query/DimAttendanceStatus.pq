let
    T = fnLoadCsv("DimAttendanceStatus.csv", {
        {"StatusCode", type text}, {"StatusLabel", type text}, {"IsExpected", Int64.Type},
        {"IsAttended", Int64.Type}, {"SortOrder", Int64.Type}})
in
    T
