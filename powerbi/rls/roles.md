# أمان مستوى الصف (RLS) في Power BI

## الأدوار وربطها بصلاحيات التطبيق

| دور Power BI | دور التطبيق | ما يراه | الفلتر |
|---|---|---|---|
| HR | `hr` | كل المؤسسة | بدون فلتر |
| Department Manager | `manager` | موظفو الأقسام التي يديرها + سجله الشخصي | `DimEmployee` عبر جدول `SecurityManagerDepartment` |
| Employee | `employee` | سجله فقط، بدون حالات المراجعة أو درجات النموذج | `DimEmployee[UserPrincipalName] = USERPRINCIPALNAME()` |

نص الفلاتر في `roles.dax`.

## كيف تُربط هوية المستخدم بالصلاحية

1. عمود `DimEmployee[UserPrincipalName]` هو البريد الوظيفي بأحرف صغيرة. يجب أن يطابق حساب Microsoft Entra ID الذي يسجّل به الموظف في Power BI Service. في البيانات الاصطناعية النطاق `example.com`، وفي بيئة حقيقية يُستبدل بالبريد الفعلي.
2. جدول `SecurityManagerDepartment` يربط بريد كل مدير بمفتاح القسم الذي يديره. يُصدَّر من حقل «مدير القسم» في التطبيق. أي تغيير لمدير القسم في التطبيق يظهر في Power BI بعد التصدير والتحديث التاليين.
3. الملف `output/powerbi/validation/SecurityRoleAssignment.csv` يوضح دور كل مستخدم في التطبيق. استخدمه مرجعًا عند إسناد الأعضاء إلى الأدوار في Power BI Service. **لا يُحمَّل إلى النموذج.**

## الإعداد في Power BI Service

1. انشر التقرير، ثم افتح Dataset/Semantic model > Security.
2. أسند إلى كل دور مجموعات أمان (Security groups) بدل الأفراد متى أمكن: مجموعة HR، ومجموعة مديري الأقسام، ومجموعة الموظفين.
3. **مهم:** RLS يُطبَّق فقط على من لديهم صلاحية Viewer في مساحة العمل أو من يصلهم التقرير عبر App أو مشاركة. أصحاب أدوار Admin وMember وContributor يرون كل البيانات. لا تمنح هذه الأدوار إلا لفريق BI. (تحقق من وثائق Microsoft الحالية لأن السلوك قد يتغير.)
4. المستخدم الذي لا ينتمي لأي دور لا يرى أي بيانات عند تفعيل RLS.

## خطوات التحقق

1. في Power BI Desktop: Modeling > View as > فعّل **Other user** واكتب `e0001@example.com` واختر الدور **Department Manager**.
   - المتوقع: قسم Operations فقط. عدد الموظفين ومعدل الحضور للشهر يطابقان سطر Operations في `validation/expected_kpis.csv`.
2. View as > `e0002@example.com` مع الدور **Employee**:
   - المتوقع: موظف واحد، وصفحة الحالات فارغة، ولا درجات نموذج.
3. View as > `e0071@example.com` مع الدور **Department Manager** (مدير IT): لا يظهر أي موظف من Operations.
4. View as > بريد غير موجود مع الدور **Employee**: لا بيانات.
5. تحقق أن جدول `SecurityManagerDepartment` مخفي ولا توجد له علاقات.

> RLS في Power BI طبقة حماية مستقلة عن صلاحيات تطبيق Flask. كلتاهما مطبّقة على الخادم، ولا تعتمد أي منهما على إخفاء عناصر الواجهة.
