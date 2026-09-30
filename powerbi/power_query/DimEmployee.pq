let
    T = fnLoadCsv("DimEmployee.csv", {
        {"EmployeeKey", Int64.Type}, {"EmployeeCode", type text}, {"EmployeeName", type text},
        {"UserPrincipalName", type text}, {"JobTitle", type text}, {"DepartmentKey", Int64.Type},
        {"DepartmentCode", type text}, {"DepartmentName", type text}, {"ManagerEmployeeKey", Int64.Type},
        {"HireDate", type date}, {"TerminationDate", type date}, {"IsActive", Int64.Type}, {"IsSynthetic", Int64.Type}}),
    // RLS compares with USERPRINCIPALNAME(); store the UPN in lower case once, here
    Lower = Table.TransformColumns(T, {{"UserPrincipalName", each if _ = null then null else Text.Lower(_), type text}})
in
    Lower
