// Security mapping for the Department Manager RLS role. Hide this table in report view and keep it
// DISCONNECTED (no relationships); the role filter reads it with FILTER().
let
    T = fnLoadCsv("SecurityManagerDepartment.csv", {{"UserPrincipalName", type text}, {"DepartmentKey", Int64.Type}}),
    Lower = Table.TransformColumns(T, {{"UserPrincipalName", Text.Lower, type text}})
in
    Lower
