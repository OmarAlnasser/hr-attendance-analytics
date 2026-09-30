// Grain: one row per employee per shift date (a night shift belongs to the date it starts).
let
    T = fnLoadCsv("FactAttendanceDaily.csv", {
        {"EmployeeKey", Int64.Type}, {"DateKey", Int64.Type}, {"ShiftKey", Int64.Type}, {"StatusCode", type text},
        {"IsExpected", Int64.Type}, {"IsAttended", Int64.Type}, {"IsAbsent", Int64.Type}, {"IsIncomplete", Int64.Type},
        {"IsLate", Int64.Type}, {"LateMinutes", Int64.Type}, {"EarlyLeaveMinutes", Int64.Type},
        {"PresenceSpanMinutes", type number}, {"ScheduledMinutes", Int64.Type}, {"PunchCount", Int64.Type},
        {"LeaveType", type text}})
in
    T
