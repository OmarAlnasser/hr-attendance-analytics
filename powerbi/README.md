# بناء تقرير Power BI

> **لا يتضمن المشروع ملف `.pbix`.** بيئة البناء لا تحتوي Power BI Desktop، فلم يكن ممكنًا إنشاء الملف أو التحقق منه. المرفق هو كل ما يلزم لبنائه خلال قرابة ساعة:
> - بيانات النموذج النجمي بصيغة CSV.
> - استعلامات Power Query بلغة M.
> - مقاييس DAX.
> - أدوار RLS.
> - مواصفات الصفحات.
> - ملف أرقام مرجعية للتحقق.

## المحتويات

| المسار | المحتوى |
|---|---|
| `power_query/*.pq` | معامل `DataFolder`، والدالة `fnLoadCsv`، واستعلام لكل جدول، واستعلام فحص `Validation_Orphans` |
| `dax/measures.dax` | كل المقاييس مع تعريفها التجاري، ومقاماتها، وطريقة التعامل مع القيم الفارغة |
| `rls/roles.dax`، `rls/roles.md` | أدوار HR وDepartment Manager وEmployee، وخطوات اختبارها |
| `pages_spec.md` | الصفحات الست والمرئيات والحقول |
| `../output/powerbi/` | ملفات CSV الناتجة من `python -m hr_analytics export-powerbi`. توجد نسخة جاهزة في `../samples/powerbi/` للبدء دون تشغيل شيء |
| `../output/powerbi/validation/expected_kpis.csv` | أرقام محسوبة بـ Python لكل شهر وقسم، للمطابقة مع DAX |

## النموذج (Star schema)

```
                 DimDate (DateKey, Date: Mark as date table)
        ┌──────────────┬───────────────┬──────────────┬──────────────┐
        │ DateKey      │ PeriodDateKey │ PeriodDateKey│ PeriodDateKey│ TargetPeriodDateKey
 FactAttendanceDaily  FactPerformance  FactEmployee   FactReview     FactRiskScore
        │             Monthly          Month          Flag           │
        └──────────────┴───────────────┴──────────────┴──────────────┘
                       DimEmployee (EmployeeKey)  ← فلاتر RLS هنا
 DimShift (ShiftKey) → FactAttendanceDaily ← DimAttendanceStatus (StatusCode)

 SecurityManagerDepartment   مخفي وبلا علاقات (يقرؤه دور المدير فقط)
 ExportInfo                  بلا علاقات (بيانات وصفية)
```

### حبيبة كل جدول (Grain)

| الجدول | الحبيبة |
|---|---|
| `FactAttendanceDaily` | موظف × تاريخ الوردية. الوردية الليلية تُنسب لتاريخ بدايتها |
| `FactPerformanceMonthly` | موظف × شهر مُقيَّم. `PeriodDateKey` هو أول يوم في الشهر |
| `FactEmployeeMonth` | موظف × شهر كان فيه على رأس العمل. مقام تغطية التقييم |
| `FactReviewFlag` | موظف × شهر × قاعدة مراجعة مفعّلة |
| `FactRiskScore` | موظف × الشهر المستهدف. تجريبي، وقد يكون فارغًا |

### العلاقات

كل العلاقات **واحد إلى متعدد، باتجاه تصفية واحد** (من البُعد إلى الحقيقة):

- `DimEmployee[EmployeeKey]` ← كل جداول الحقائق.
- `DimDate[DateKey]` ← `FactAttendanceDaily[DateKey]`، و`PeriodDateKey` في الجداول الشهرية، و`FactRiskScore[TargetPeriodDateKey]`.
- `DimShift[ShiftKey]` ← `FactAttendanceDaily[ShiftKey]`.
- `DimAttendanceStatus[StatusCode]` ← `FactAttendanceDaily[StatusCode]`.

لا توجد علاقات بين جداول الحقائق ولا علاقات ثنائية الاتجاه. لهذا لا يحدث عدّ مزدوج: كل مقياس يعدّ صفوف جدول حقائق واحد بحبيبته المعلنة. مثال: `[Avg Weighted Score]` لا يتكرر بعدد أيام الحضور لأنه لا يمر عبر `FactAttendanceDaily`.

`DimEmployee` يحمل القسم **الحالي** للموظف (SCD Type 1)، مثل صلاحيات التطبيق. إذا انتقل موظف بين قسمين، يظهر تاريخه كله تحت القسم الجديد. هذا قيد موثّق في `docs/assumptions.md`.

## خطوات البناء

1. شغّل `python -m hr_analytics export-powerbi`. تُكتب الملفات في `output/powerbi/`.
2. في Power BI Desktop: Get data > Blank query. أنشئ المعامل `DataFolder` من الملف `00_DataFolder_parameter.pq`، واجعل قيمته مسار المجلد **مع شرطة مائلة في النهاية**.
3. أنشئ استعلامًا فارغًا باسم `fnLoadCsv` والصق محتوى الملف المقابل.
4. لكل ملف `.pq` آخر: أنشئ Blank query بنفس اسم الملف والصق المحتوى.
5. ألغِ Enable load للاستعلامين `fnLoadCsv` و`Validation_Orphans`. افتح `Validation_Orphans` وتأكد أنه **فارغ**.
6. Close & Apply، ثم في Model view:
   - أنشئ العلاقات الموضحة أعلاه.
   - علّم `DimDate` كجدول تاريخ على العمود `Date`. هذا ضروري لعمل `DATEADD` في مقاييس التغير الشهري.
   - اضبط الترتيب: `MonthName` حسب `MonthNumber`، و`YearMonth` حسب `YearMonthSort`، و`DayOfWeekName` حسب `DayOfWeekNumber`، و`StatusLabel` حسب `SortOrder`.
   - أخفِ `SecurityManagerDepartment` وأعمدة المفاتيح في جداول الحقائق.
7. أنشئ معاملات What-if من Modeling > New parameter > Numeric range:
   - `Low Score Threshold`: من 1 إلى 5 بخطوة 0.1، والافتراضي 3.
   - `Small Sample Threshold`: من 2 إلى 20 بخطوة 1، والافتراضي 5.
   - `Risk Cutoff`: من 0.1 إلى 0.9 بخطوة 0.05، والافتراضي 0.5.
   - اختياريًا `W Punctuality` و`W Communication` و`W Task Completion` و`W Teamwork`: من 0 إلى 100 بخطوة 5.
8. أنشئ جدول `_Measures` وأضف المقاييس من `dax/measures.dax`. التعليق فوق كل مجموعة يحدد مجلد العرض (Display folder).
9. أنشئ الأدوار من `rls/roles.dax` واختبرها كما في `rls/roles.md`.
10. ابنِ الصفحات حسب `pages_spec.md`.

## التحقق (Validation)

قارن مرئيًا جدوليًا بالملف `validation/expected_kpis.csv`. هذا الملف محسوب بنفس دوال Python التي يستخدمها التطبيق والتقرير الشهري.

1. أنشئ مصفوفة بالصفوف `DimDate[YearMonth]` و`DimEmployee[DepartmentName]`، والقيم `[Expected Days]` و`[Attended Days]` و`[Late Days]` و`[Attendance Rate]` و`[Late Rate]` و`[Evaluations]` و`[Avg Weighted Score]`.
2. طابق 3 أشهر على الأقل مع ملف المطابقة، لكل الأقسام ولسطر `(All)`. يجب أن تتطابق الأعداد تمامًا، والمعدلات حتى 4 منازل عشرية.
3. الاختبار الآلي `tests/test_end_to_end.py` يعيد نفس حساب المقاييس (مجموع `IsAttended` مقسومًا على مجموع `IsExpected`) من ملفات CSV، ويتحقق من مطابقته لأرقام التطبيق. هذا يثبت أن الملفات المصدّرة تكفي لإنتاج الأرقام نفسها. **مطابقة DAX داخل Power BI نفسه تبقى خطوة يدوية**، لأنها لم تُنفَّذ في بيئة البناء.
4. تأكد أن صف الإجمالي في مصفوفة الأقسام يساوي سطر `(All)`، وليس متوسط معدلات الأقسام.

## التحديث (Refresh): ما الذي يُحدَّث ومتى

هناك عمليتا تحديث منفصلتان، **ولا يوجد تحديث لحظي**:

| الطبقة | ما يحدث | كيف يُشغَّل |
|---|---|---|
| تطبيق Flask | استيراد ملف البصمات ثم إعادة حساب الأيام المتأثرة في SQLite | عند رفع ملف من صفحة الاستيراد، أو بالأمر `import-punches`، أو بجدولة (انظر `scripts/`) |
| ملفات Power BI | إعادة كتابة ملفات CSV من قاعدة البيانات | الأمر `export-powerbi`، ويُجدول بعد الاستيراد |
| نموذج Power BI | قراءة ملفات CSV من جديد | Desktop: زر Refresh يدويًا. Service: تحديث مجدول |

- **Power BI Service** لا يصل إلى ملفات على جهاز محلي إلا عبر **On-premises data gateway**، ويجب أن يكون الجهاز الذي يعمل عليه الـ gateway متاحًا وقت التحديث.
- عدد مرات التحديث المجدول محدود حسب الترخيص: قرابة 8 مرات يوميًا مع Pro، وحتى 48 مع Premium/PPU/Fabric. **تحقق من الحدود الحالية في وثائق Microsoft.**
- التسلسل المقترح يوميًا:
  - 00:30 استيراد ملفات الجهاز من مجلد التسليم.
  - 00:45 تشغيل `export-powerbi`.
  - 02:00 تحديث Power BI المجدول.
- البيانات في التقرير عمرها يوم كحد أقصى. هذا تحديث دوري لملفات، **وليس «real-time»**، ولا يجوز تسميته كذلك.
- DirectQuery غير ممكن مع SQLite. عند الانتقال إلى SQL Server أو PostgreSQL (انظر `docs/production_migration.md`)، يمكن ربط Power BI بالقاعدة مباشرة في وضع Import، أو DirectQuery إذا لزم. عندها تُستبدل استعلامات CSV باستعلامات على views تحمل نفس أسماء الأعمدة، وتبقى المقاييس والأدوار كما هي.
