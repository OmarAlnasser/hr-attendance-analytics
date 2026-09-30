let
    T = fnLoadCsv("DimDate.csv", {
        {"Date", type date}, {"DateKey", Int64.Type}, {"Year", Int64.Type}, {"MonthNumber", Int64.Type},
        {"MonthName", type text}, {"YearMonth", type text}, {"YearMonthSort", Int64.Type}, {"MonthStart", type date},
        {"DayOfWeekNumber", Int64.Type}, {"DayOfWeekName", type text}, {"WeekStart", type date},
        {"IsWeekend", Int64.Type}, {"IsPublicHoliday", Int64.Type}, {"HolidayName", type text}})
in
    T
// After loading: Mark as date table on [Date]; sort MonthName by MonthNumber, YearMonth by YearMonthSort,
// DayOfWeekName by DayOfWeekNumber (1 = Sunday, the first day of the Saudi work week).
