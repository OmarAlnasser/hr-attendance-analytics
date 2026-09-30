# مواصفات صفحات تقرير Power BI

أسماء الحقول والمقاييس بالإنجليزية كما في النموذج. كل صفحة تحتوي على:
- بطاقة `[Data Label]` في الأعلى، تعرض تنبيه «بيانات اصطناعية» تلقائيًا.
- قطّاعات (Slicers) موحدة على اليمين: `DimDate[YearMonth]` (اختيار واحد)، و`DimEmployee[DepartmentName]`.

اجعل القطّاعات متزامنة بين الصفحات من View > Sync slicers.

الألوان مطابقة للتطبيق حتى تبقى لغة الحالات واحدة: حاضر `#3A8F6B`، متأخر `#D99A1E`، غائب `#C2453D`، بصمة واحدة `#7A5BB5`، إجازة `#3D7CC9`.

---

## 1) الملخص التنفيذي (Executive summary)

**الغرض:** صورة الشهر المختار في أقل من دقيقة.

| العنصر | الحقول |
|---|---|
| شريط مؤشرات (Multi-row card أو 6 بطاقات) | `[Attendance Rate]`، `[Absence Rate]`، `[Late Rate]`، `[Evaluation Coverage]`، `[Avg Weighted Score]`، `[Employees Flagged]` |
| التغير الشهري تحت كل مؤشر | `[Attendance Rate MoM Change]`، `[Avg Score MoM Change]` (تنسيق +0.0%؛ فارغ إذا لم يوجد شهر سابق) |
| خط: الحضور والتأخر آخر 12 شهرًا | المحور `DimDate[YearMonth]` (مرتب بـ YearMonthSort)؛ القيم `[Attendance Rate]` و`[Late Rate]`. عطّل تأثير قطّاع الشهر على هذا المرئي عبر Edit interactions |
| خط: متوسط الدرجة | `DimDate[YearMonth]` × `[Avg Weighted Score]`، مع خط ثابت عند `[Low Score Threshold Value]` |
| نص أسفل الصفحة | تعريفات مختصرة للمعدلات ومقاماتها |

## 2) الحضور والتأخر والغياب

| العنصر | الحقول |
|---|---|
| مؤشرات | `[Expected Days]`، `[Attended Days]`، `[Absent Days]`، `[Late Days]`، `[Avg Late Minutes]`، `[Incomplete Rate]`، `[Avg Presence Span (h)]` بعنوان «مدة التواجد (ليست ساعات عمل مؤكدة)» |
| أعمدة مكدسة: توزيع الحالات يوميًا | المحور `DimDate[Date]`؛ الوسيلة `DimAttendanceStatus[StatusLabel]` (مرتب بـ SortOrder)؛ القيمة عدد صفوف FactAttendanceDaily |
| جدول: حسب الوردية | `DimShift[ShiftName]`، `[Attendance Rate]`، `[Late Rate]`، `[Avg Late Minutes]` |
| جدول تفصيلي | `DimDate[Date]`، `DimEmployee[EmployeeCode]`، `DimEmployee[EmployeeName]`، `DimAttendanceStatus[StatusLabel]`، `FactAttendanceDaily[LateMinutes]`، `FactAttendanceDaily[LeaveType]` مع فلتر مستوى المرئي StatusCode ∈ {absent, incomplete} أو IsLate = 1 |

## 3) ملف الموظف (Employee profile)

**الغرض:** صفحة Drillthrough على `DimEmployee[EmployeeCode]`، يُوصل إليها بالنقر الأيمن من أي جدول.

| العنصر | الحقول |
|---|---|
| بطاقة الهوية | `EmployeeName`، `JobTitle`، `DepartmentName`، `HireDate`، `TerminationDate` |
| مصفوفة الشهر يومًا بيوم | الصفوف فارغة، الأعمدة `DimDate[Date]` (يوم الشهر)، القيمة `FIRSTNONBLANK(FactAttendanceDaily[StatusCode], 1)` مع تلوين خلفية حسب الحالة. تحاكي «شريط الشهر» في التطبيق |
| خطان شهريان | `[Attendance Rate]` و`[Late Rate]` ثم `[Avg Weighted Score]`، على `DimDate[YearMonth]` لآخر 12 شهرًا |
| جدول التقييمات | `FactPerformanceMonthly[Period]`، الدرجات الأربع، `WeightedScore`، والأوزان المستخدمة `Weight*` |

## 4) مقارنة الأقسام (Department comparison)

| العنصر | الحقول |
|---|---|
| جدول/مصفوفة | `DimEmployee[DepartmentName]`، `[Employees With Records]`، `[Expected Days]`، `[Attendance Rate]`، `[Absence Rate]`، `[Late Rate]`، `[Avg Weighted Score]`، `[Evaluation Coverage]`، `[Small Sample Flag]` |
| أعمدة أفقية | `DepartmentName` × `[Attendance Rate]` و`[Late Rate]` |
| ملاحظة ثابتة | «المعدلات مجمّعة على الأيام المتوقعة؛ الأقسام الموسومة بـ * لديها أقل من N موظفين وتُقرأ بحذر.» |

> لا تستخدم متوسط معدلات الموظفين (AVERAGEX على الموظفين) للمقارنة. القسم ذو الموظفين القلائل سيهيمن على النتيجة. المقاييس المجمّعة تعطي كل يوم متوقع الوزن نفسه.

## 5) الخريطة الحرارية: اليوم × الأسبوع

| العنصر | الحقول |
|---|---|
| مصفوفة | الصفوف `DimDate[WeekStart]`؛ الأعمدة `DimDate[DayOfWeekName]` (مرتب بـ DayOfWeekNumber: الأحد = 1)؛ القيمة `[Attendance Rate]` |
| تنسيق شرطي | خلفية بتدرج لوني (أحمر `#D9776F` عند 80% أو أقل، أصفر `#F1D08A` عند 90%، أخضر `#2F7D5D` عند 100%). الخلايا الفارغة (الجمعة والسبت عادة) تبقى فارغة ولا تُعرض 0% |
| مصفوفة ثانية اختيارية | نفس المحاور مع `[Late Rate]` |

## 6) حالات تحتاج مراجعة (Review cases)

**تُعرض فقط لدوري HR وDepartment Manager.** دور Employee يرى جداول فارغة بسبب RLS.

| العنصر | الحقول |
|---|---|
| عدد الموظفين حسب القاعدة | `FactReviewFlag[RuleDescription]` × `[Employees Flagged]` |
| جدول الحالات | `DimEmployee[EmployeeCode]`، `EmployeeName`، `DepartmentName`، `FactReviewFlag[RuleDescription]`، `FactReviewFlag[Evidence]` |
| قسم منفصل بعنوان «تجريبي» | جدول `FactRiskScore[TargetPeriod]`، `EmployeeCode`، `[Avg Risk Probability]`، مع قطّاع `Risk Cutoff` ومؤشر `[Employees Above Risk Cutoff]` |
| نص تحذيري ثابت | «القواعد مؤشرات للحوار الداعم وليست قرارات. درجات النموذج تجريبية ومبنية على ارتباطات وليست أسبابًا، ولا تُستخدم لأي إجراء تلقائي أو تأديبي.» |

صفحة الحالات تُفلتر بـ `DimDate[YearMonth]` عبر `PeriodDateKey`. درجات النموذج تُفلتر بالشهر المستهدف `TargetPeriodDateKey`.
