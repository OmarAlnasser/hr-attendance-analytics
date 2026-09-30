// Data check (do not load to the model: right-click > uncheck "Enable load").
// Lists fact rows whose keys have no match in a dimension. Expected result: an empty table.
let
    Emp   = List.Buffer(DimEmployee[EmployeeKey]),
    Dates = List.Buffer(DimDate[DateKey]),
    A = Table.AddColumn(Table.SelectRows(FactAttendanceDaily,
            each not List.Contains(Emp, [EmployeeKey]) or not List.Contains(Dates, [DateKey])),
            "Problem", each "FactAttendanceDaily key without dimension row"),
    P = Table.AddColumn(Table.SelectRows(FactPerformanceMonthly,
            each not List.Contains(Emp, [EmployeeKey]) or not List.Contains(Dates, [PeriodDateKey])),
            "Problem", each "FactPerformanceMonthly key without dimension row"),
    Dups = Table.SelectRows(Table.Group(FactAttendanceDaily, {"EmployeeKey", "DateKey"},
            {{"Rows", each Table.RowCount(_), Int64.Type}}), each [Rows] > 1),
    D = Table.AddColumn(Dups, "Problem", each "Duplicate employee x date (grain broken)"),
    Result = Table.Combine({
        Table.SelectColumns(A, {"EmployeeKey", "Problem"}),
        Table.SelectColumns(P, {"EmployeeKey", "Problem"}),
        Table.SelectColumns(D, {"EmployeeKey", "Problem"})})
in
    Result
