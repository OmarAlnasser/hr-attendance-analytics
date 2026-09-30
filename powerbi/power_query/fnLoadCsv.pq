// Function: fnLoadCsv  (create as a blank query named fnLoadCsv, then paste)
// Reads one exported CSV (UTF-8, comma separated, header row) and applies column types
// using the en-US culture, so dates (yyyy-MM-dd) and decimals (.) parse the same on any PC locale.
(fileName as text, types as list) as table =>
let
    // One static data source (the folder) instead of a path built per file: this keeps the dataset
    // refreshable through an on-premises data gateway (paths computed at run time count as a
    // "dynamic data source" in the Power BI service).
    Files    = Folder.Files(DataFolder),
    Content  = Files{[Name = fileName, #"Folder Path" = DataFolder]}[Content],
    Source   = Csv.Document(Content, [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    // fail loudly if the export changed shape instead of silently loading nulls
    Missing  = List.Difference(List.Transform(types, each _{0}), Table.ColumnNames(Promoted)),
    Checked  = if List.IsEmpty(Missing) then Promoted
               else error Error.Record("Export changed", "Missing columns in " & fileName, Text.Combine(Missing, ", ")),
    // empty strings become null before typing (blank TerminationDate, LeaveType, ...)
    Nulls    = Table.ReplaceValue(Checked, "", null, Replacer.ReplaceValue, Table.ColumnNames(Checked)),
    Typed    = Table.TransformColumnTypes(Nulls, types, "en-US")
in
    Typed
