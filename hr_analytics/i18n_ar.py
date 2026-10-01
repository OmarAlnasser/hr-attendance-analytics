"""Arabic wording for every sentence in the interface.

Keys are the English sentences exactly as they appear in the code and the
templates; values are written as Arabic in their own right rather than
word-for-word translations:

* Modern Standard Arabic in the plain register used by Saudi HR systems
  (حضور، انصراف، بصمة، إجازة، مسير).
* Neutral about the reader's gender: instructions use "يُرجى" with a verbal
  noun, buttons use verbal nouns (حفظ، عرض، اعتماد), and "you" is written
  without vowel marks.
* Counted nouns avoid case-ending traps: a number usually follows a colon
  ("أيام الغياب: 3"), or the count is built by i18n.count() with the right
  number agreement.
* Placeholders such as {n} and {date} must stay exactly as in English;
  tests/test_i18n.py checks that, and that no sentence is missing.
"""
from __future__ import annotations

AR: dict[str, str] = {}

# ------------------------------------------------------------------ shell, sign-in, errors
AR.update({
    "Attendance and performance": "الحضور والأداء",
    "Attendance and Performance": "الحضور والأداء",
    "Find an employee…": "البحث عن موظف…",
    "Search by name, employee code or badge": "البحث بالاسم أو الرقم الوظيفي أو رقم البطاقة",
    "Find an employee": "البحث عن موظف",
    "Main menu": "القائمة الرئيسية",
    "My month": "شهري",
    "{n} waiting": "بانتظار القرار: {n}",
    "{n} open": "طلبات مفتوحة: {n}",
    "Data and settings": "البيانات والإعدادات",
    "User accounts": "حسابات المستخدمين",
    "Sign out": "تسجيل الخروج",
    "Public demo.": "نسخة تجريبية عامة.",
    "All people and figures are made up. Feel free to click anything, approve or reject requests and import files: "
    "the data is rebuilt every night.":
        "جميع الأسماء والأرقام هنا وهمية. يمكنك تجربة كل شيء: اعتماد الطلبات أو رفضها واستيراد الملفات، "
        "فالبيانات تُبنى من جديد كل ليلة.",
    "Demonstration data: all people and figures are made up and say nothing about a real organisation.":
        "بيانات تجريبية: جميع الأسماء والأرقام وهمية ولا تمثّل أي جهة حقيقية.",
    "Back to the start page": "العودة إلى الصفحة الرئيسية",
    "Attendance and performance, one month at a glance": "الحضور والأداء، الشهر كله في نظرة واحدة",
    "Punches from the time clock become a clear daily record using rules anyone can check, and monthly evaluations "
    "sit right beside them. Anything flagged is a reason to talk, never an automatic decision.":
        "تتحول بصمات جهاز الحضور إلى سجل يومي واضح وفق قواعد يستطيع أي شخص التحقق منها، وتظهر التقييمات "
        "الشهرية إلى جانبها. وكل ما يُشار إليه هو دعوة إلى الحوار، لا قرار تلقائي.",
    "A live demo with made-up data: 121 employees and twelve months of punches. Nothing you change is permanent; "
    "the data is rebuilt every night.":
        "نسخة تجريبية حيّة ببيانات وهمية: 121 موظفًا وبصمات اثني عشر شهرًا. لا يبقى أي تعديل، "
        "إذ تُبنى البيانات من جديد كل ليلة.",
    "Local installation. Demo accounts are created by the seed command.":
        "تثبيت محلي. تُنشأ الحسابات التجريبية بأمر تحميل البيانات (seed).",
    "Try the live demo": "تجربة النسخة التجريبية",
    "No sign-up needed. Choose a role to see exactly what that person sees; access is checked on the server for "
    "every page.":
        "لا حاجة إلى إنشاء حساب. يكفي اختيار دور لرؤية ما يراه صاحبه تمامًا، ويُتحقق من الصلاحيات على "
        "الخادم في كل صفحة.",
    "Sign in with a username and password": "الدخول باسم مستخدم وكلمة مرور",
    "Username": "اسم المستخدم",
    "Password": "كلمة المرور",
    "Sign in": "تسجيل الدخول",
    "Previous month": "الشهر السابق",
    "Next month": "الشهر التالي",
    "Your password was reset. Choose a new password to continue.":
        "أُعيد تعيين كلمة المرور. يُرجى اختيار كلمة مرور جديدة للمتابعة.",
    "This form has expired. Reload the page and try again.":
        "انتهت صلاحية هذا النموذج. يُرجى تحديث الصفحة والمحاولة مرة أخرى.",
    "Not permitted": "غير مسموح",
    "You do not have access to this data.": "ليست لديك صلاحية الاطلاع على هذه البيانات.",
    "Something in the request was not right": "في الطلب خطأ ما",
    "The request could not be processed.": "تعذّر تنفيذ الطلب.",
    "You do not have access to this page.": "ليست لديك صلاحية الدخول إلى هذه الصفحة.",
    "Not found": "غير موجود",
    "The page or record does not exist.": "الصفحة أو السجل غير موجود.",
    "File too large": "الملف كبير جدًا",
    "Uploads are limited to {mb} MB.": "الحد الأقصى لحجم الملف {mb} ميغابايت.",
    "One of the values in the address is not valid.": "إحدى القيم في عنوان الصفحة غير صحيحة.",
    "No data for this selection.": "لا توجد بيانات لهذا الاختيار.",
    "Your role does not allow this action.": "صلاحيات دورك لا تسمح بهذا الإجراء.",
    "The month must look like 2026-08 (year, then month).": "يجب كتابة الشهر بهذا الشكل: \u20662026-08\u2069 (السنة ثم الشهر).",
    "That department does not exist.": "هذا القسم غير موجود.",
    "You can only view departments you manage.": "يقتصر اطلاعك على الأقسام التي تحت إدارتك.",
    "You have signed out.": "تم تسجيل الخروج.",
    "This is a shared demo account, so its password cannot be changed.":
        "هذا حساب تجريبي مشترك، لذلك لا يمكن تغيير كلمة مروره.",
    "The current password is not right.": "كلمة المرور الحالية غير صحيحة.",
    "The new password must be at least 12 characters long.": "يجب ألا تقل كلمة المرور الجديدة عن 12 حرفًا.",
    "The two new passwords are not the same.": "كلمتا المرور الجديدتان غير متطابقتين.",
    "Choose a password that is different from the current one.": "يُرجى اختيار كلمة مرور مختلفة عن الحالية.",
    "Password changed.": "تم تغيير كلمة المرور.",
    "Too many attempts that did not work. Please wait a few minutes and try again.":
        "محاولات كثيرة لم تنجح. يُرجى الانتظار بضع دقائق ثم المحاولة مرة أخرى.",
    "Username or password is incorrect.": "اسم المستخدم أو كلمة المرور غير صحيحة.",
    "Above HR: decides on HR staff and who gets HR access, and sees the whole organisation.":
        "أعلى من الموارد البشرية: يقرّر في شؤون موظفيها وفي منح صلاحياتها، ويطّلع على المنشأة كاملة.",
    "The whole organisation: the Today board, approvals, imports, accounts and reports.":
        "المنشأة كاملة: لوحة اليوم والموافقات والاستيراد والحسابات والتقارير.",
    "One department: approve leave and punch corrections, and evaluate the team.":
        "قسم واحد: اعتماد الإجازات وتصحيحات البصمة، وتقييم أعضاء الفريق.",
    "Their own record: request leave, report a missed punch and see the month.":
        "السجل الشخصي: طلب إجازة، والإبلاغ عن بصمة منسية، ومتابعة الشهر.",
    # account page and temporary passwords
    "New password again": "تأكيد كلمة المرور الجديدة",
    "Change password": "تغيير كلمة المرور",
    "At least 12 characters. Passwords are never stored as they are typed, only as a secure hash.":
        "12 حرفًا على الأقل. لا تُحفظ كلمات المرور كما تُكتب، بل بصيغة مشفّرة آمنة.",
    "Current password": "كلمة المرور الحالية",
    "New password": "كلمة المرور الجديدة",
    "Temporary passwords: shown only once": "كلمات مرور مؤقتة: تظهر مرة واحدة فقط",
    "Give each person their password privately. It will not be shown again, and it only opens the page for "
    "choosing a new password, which they must do at their first sign-in. If one is lost, use \"Reset password\".":
        "تُسلَّم كل كلمة مرور لصاحبها على انفراد. لن تظهر مرة أخرى، ولا تفتح إلا صفحة اختيار كلمة مرور جديدة "
        "عند أول دخول. وإذا ضاعت يُستخدم زر «إعادة تعيين كلمة المرور».",
    "For": "الغرض",
    "Temporary password": "كلمة المرور المؤقتة",
    "A new account": "حساب جديد",
    "A password reset": "إعادة تعيين كلمة المرور",
})

# ------------------------------------------------------------------ overview, attendance, employee, today
AR.update({
    # overview
    "Overview": "نظرة عامة",
    "Month": "الشهر",
    "Show": "عرض",
    "Key figures for {period}": "أهم الأرقام لشهر {period}",
    "One department": "قسم واحد",
    "Whole organisation": "المنشأة كاملة",
    "The departments you manage": "الأقسام التي تحت إدارتك",
    "{n} with attendance records in {period}": "الموظفون الذين لهم سجلات حضور في {period}: {n}",
    "{a} of {b} working days": "{a} من أصل {b} من أيام العمل",
    "{n} days absent without leave": "أيام الغياب دون إجازة: {n}",
    "Late on {n} of the days attended": "التأخر في {n} من أيام الحضور",
    "On late days, counted from the shift start": "في أيام التأخر فقط، محسوبًا من بداية الوردية",
    "Evaluations done": "التقييمات المنجزة",
    "{a} of {b} employees due an evaluation": "{a} من أصل {b} من الموظفين المستحق تقييمهم",
    "Weighted, on a scale of 1 to 5": "درجة موزونة على مقياس من 1 إلى 5",
    "Needs review": "تستحق المراجعة",
    "{n} this month": "هذا الشهر: {n}",
    "{n} shifts had not finished when the data was processed, so they are not counted as absences yet.":
        "لم تكن {n} من الورديات قد انتهت عند معالجة البيانات، لذلك لا تُحتسب غيابًا حتى الآن.",
    "Attendance over the last 12 months": "الحضور خلال آخر 12 شهرًا",
    "All working days in the period counted together": "جميع أيام العمل في الفترة محسوبة معًا",
    "Average performance score": "متوسط درجة الأداء",
    "Scores below {t} are flagged for review": "يُشار للمراجعة إلى كل درجة أقل من {t}",
    "Departments in {period}": "الأقسام في {period}",
    "Rates make departments of different sizes comparable. * Fewer than {n} employees, so treat with care.":
        "النِّسب تجعل الأقسام المختلفة الأحجام قابلة للمقارنة. * يعني أن عدد الموظفين أقل من {n}، "
        "فتُقرأ أرقامه بحذر.",
    "Evaluations": "التقييمات",
    "There is no attendance for this month yet. Import punches or choose another month.":
        "لا توجد بيانات حضور لهذا الشهر بعد. يُرجى استيراد البصمات أو اختيار شهر آخر.",
    "Attendance by week and weekday": "الحضور حسب الأسبوع واليوم",
    "Share of working days attended. Hatched cells had no working days.":
        "نسبة أيام العمل التي حضرها الموظفون. الخانات المخطّطة لم يكن فيها أيام عمل.",
    "Week starting": "بداية الأسبوع",
    "98% or more": "98% فأكثر",
    "95% to 98%": "من 95% إلى 98%",
    "90% to 95%": "من 90% إلى 95%",
    "80% to 90%": "من 80% إلى 90%",
    "Below 80%": "أقل من 80%",
    "No working days in this selection.": "لا توجد أيام عمل في هذا الاختيار.",
    "How these figures are counted: a working day is a scheduled shift within the employment dates that is not "
    "approved leave or a public holiday, and whose shift has ended. A day counts as attended when there is at "
    "least one punch. Late means the first punch came after the shift start plus the grace period. The time "
    "between first and last punch is presence, not verified working hours.":
        "طريقة الاحتساب: يوم العمل هو وردية مجدولة ضمن فترة التوظيف، ليست إجازة معتمدة ولا إجازة رسمية، "
        "وقد انتهى وقتها. ويُعدّ اليوم حضورًا إذا سُجّلت فيه بصمة واحدة على الأقل. والتأخر أن تأتي البصمة "
        "الأولى بعد بداية الوردية ومدة السماح. أما المدة بين البصمة الأولى والأخيرة فهي مدة تواجد، "
        "وليست ساعات عمل مؤكدة.",
    "Late rate (of days attended)": "نسبة التأخر (من أيام الحضور)",
    "No employee record": "لا يوجد سجل موظف",
    "This account is not linked to an employee record.": "هذا الحساب غير مرتبط بسجل موظف.",
    # daily attendance
    "Daily attendance": "الحضور اليومي",
    "One row for each employee and day. A night shift belongs to the day it starts.":
        "صف لكل موظف في كل يوم. والوردية الليلية تُحتسب لليوم الذي تبدأ فيه.",
    "Code or name": "الرقم الوظيفي أو الاسم",
    "Download CSV": "تنزيل ملف CSV",
    "Download Excel": "تنزيل ملف Excel",
    "{n} of the days attended": "{n} من أيام الحضور",
    "Average presence": "متوسط مدة التواجد",
    "{h} h": "{h} ساعة",
    "First to last punch, not verified working hours": "من البصمة الأولى إلى الأخيرة، وليست ساعات عمل مؤكدة",
    "The figures above cover every day in the date range; the status filter only narrows the table.":
        "تشمل الأرقام أعلاه جميع أيام الفترة المختارة، أما فلتر الحالة فيقتصر أثره على الجدول.",
    "Showing the first {n}. Download the file for the full list.":
        "يُعرض أول {n} صف فقط. للقائمة الكاملة يُرجى تنزيل الملف.",
    "Left early (min)": "الانصراف المبكر (دقيقة)",
    "No days match these filters.": "لا توجد أيام مطابقة لهذه الفلاتر.",
    "Any": "الكل",
    "All departments I can see": "كل الأقسام المتاحة لي",
    "Item": "البند",
    "Dates": "التواريخ",
    "Search": "البحث",
    "Downloaded by": "نزّله",
    "Note": "ملاحظة",
    "Made-up demonstration data. Hours present run from the first to the last punch and are not verified working "
    "hours.":
        "بيانات تجريبية وهمية. ساعات التواجد محسوبة من البصمة الأولى إلى الأخيرة، وليست ساعات عمل مؤكدة.",
    "You can only see people within your area.": "يقتصر اطلاعك على الأشخاص ضمن نطاق مسؤوليتك.",
    "Not employed": "خارج فترة التوظيف",
    "Not calculated yet": "لم يُحتسب بعد",
    "{n} min late": "تأخر {n} د",
    "Name": "الاسم",
    "Employee code": "الرقم الوظيفي",
    "Date": "التاريخ",
    "Status": "الحالة",
    "Shift": "الوردية",
    "Clock-in": "الدخول",
    "Clock-out": "الخروج",
    "Minutes late": "دقائق التأخر",
    "Left early (minutes)": "الانصراف المبكر (دقيقة)",
    "Hours present": "ساعات التواجد",
    "Notes": "ملاحظات",
    "Yes": "نعم",
    "Please enter a valid date.": "يُرجى إدخال تاريخ صحيح.",
    "Choose a range of at most 400 days.": "يُرجى اختيار فترة لا تزيد على 400 يوم.",
    "That status is not recognised.": "هذه الحالة غير معروفة.",
    # one employee
    "Evaluate {period}": "تقييم {period}",
    "Edit record": "تعديل السجل",
    "My requests": "طلباتي",
    "{period}, day by day": "{period} يومًا بيوم",
    "Joined {date}": "تاريخ الالتحاق: {date}",
    "Left {date}": "تاريخ ترك العمل: {date}",
    "Attendance for each day": "الحضور في كل يوم",
    "Days absent": "أيام الغياب",
    "Without approved leave": "دون إجازة معتمدة",
    "Days late": "أيام التأخر",
    "{n} minutes late on average": "متوسط التأخر بالدقائق: {n}",
    "Days with a missing punch": "أيام البصمة الناقصة",
    "No clock-in or no clock-out": "لا توجد بصمة دخول أو بصمة خروج",
    "Leave and holidays": "الإجازات والعطل الرسمية",
    "Not counted against attendance": "لا تُحتسب على الحضور",
    "Attendance trend": "اتجاه الحضور",
    "Performance score trend": "اتجاه درجة الأداء",
    "Days worth a look": "أيام تستحق النظر",
    "Late arrivals, absences, missing punches, leave, holidays and work on days off":
        "التأخر والغياب والبصمات الناقصة والإجازات والعطل الرسمية والعمل في أيام الراحة",
    "Correction pending": "التصحيح بانتظار القرار",
    "Report a missed punch": "الإبلاغ عن بصمة منسية",
    "Nothing unusual this month.": "لا شيء غير معتاد هذا الشهر.",
    "Evaluations in the last 12 months": "التقييمات خلال آخر 12 شهرًا",
    "Each score uses the weights that applied when it was saved": "تُحسب كل درجة بالأوزان التي كانت سارية عند حفظها",
    "Evaluated by": "المقيِّم",
    "History": "السجل",
    "No evaluations in the last 12 months.": "لا توجد تقييمات خلال آخر 12 شهرًا.",
    "Punch corrections this month": "تصحيحات البصمة هذا الشهر",
    "Day": "اليوم",
    "Missed": "البصمة المنسية",
    "Time": "الوقت",
    "Decided by": "صاحب القرار",
    "No job title": "دون مسمى وظيفي",
    "{shift}, {start} to {end}, {grace} minutes grace": "{shift} من {start} إلى {end}، ومدة السماح بالدقائق: {grace}",
    "Leave": "الإجازات",
    "Request leave or report a missed punch": "طلب إجازة أو الإبلاغ عن بصمة منسية",
    "Type": "النوع",
    "From": "من",
    "To": "إلى",
    "Edit": "تعديل",
    # today board
    "Today": "اليوم",
    "Looking back": "استعراض لحظة سابقة",
    "as of {time}": "حتى الساعة {time}",
    "updates every minute": "يتحدّث كل دقيقة",
    "punches after this time are left out": "البصمات بعد هذا الوقت غير محتسبة",
    "Back to now": "العودة إلى الآن",
    "The most recent punch received was at {time}. Punches arrive when a device file is imported, so people with "
    "no punch after that time may simply not have been loaded yet; it does not mean they are absent.":
        "آخر بصمة وصلت كانت في {time}. تصل البصمات عند استيراد ملف الجهاز، فمن لا تظهر له بصمة بعد هذا الوقت "
        "ربما لم تُحمَّل بصمته بعد، وهذا لا يعني أنه غائب.",
    "No punches have been imported yet.": "لم تُستورد أي بصمات حتى الآن.",
    "See {date} at 09:30": "عرض {date} عند الساعة 09:30",
    "Scheduled to work": "المجدول دوامهم",
    "A working shift on this date": "لديهم وردية عمل في هذا التاريخ",
    "At work": "على رأس العمل",
    "{n} of them arrived late": "المتأخرون منهم: {n}",
    "Not in yet": "لم يحضروا بعد",
    "Past the start time and grace period, no punch": "تجاوز الوقت البداية ومدة السماح دون بصمة",
    "Due later": "دوامهم لاحقًا",
    "Their shift has not started": "لم تبدأ ورديتهم بعد",
    "Left for the day": "انصرفوا",
    "Clock-in and clock-out recorded": "سُجّلت بصمة الدخول والخروج",
    "On leave or off": "في إجازة أو راحة",
    "Approved leave / day off or holiday": "إجازة معتمدة / يوم راحة أو إجازة رسمية",
    "No one": "لا أحد",
    "Off today ({n})": "في راحة اليوم ({n})",
    "Weekly day off or public holiday": "الراحة الأسبوعية أو الإجازة الرسمية",
    "The same rules as the monthly figures apply: late means the first punch came after the shift start plus the "
    "grace period, and a night shift belongs to the day it starts. Nothing on this page is saved; the nightly run "
    "records the final result.":
        "تنطبق هنا قواعد الأرقام الشهرية نفسها: التأخر أن تأتي البصمة الأولى بعد بداية الوردية ومدة السماح، "
        "والوردية الليلية تُحتسب لليوم الذي تبدأ فيه. لا يُحفظ شيء من هذه الصفحة، فالمعالجة الليلية هي التي "
        "تسجّل النتيجة النهائية.",
    "Arrived late": "حضروا متأخرين",
    "In, on time": "حضروا في الموعد",
    "Expected later": "متوقعون لاحقًا",
    "Clocked out": "سجّلوا الانصراف",
    "On leave": "في إجازة",
    "Day off": "يوم راحة",
    "Working on a day off, in at {time}": "عمل في يوم راحة، الدخول {time}",
    "Due at {time}": "بداية الدوام {time}",
    "No punch for the whole shift": "لا توجد بصمة طوال الوردية",
    "{n} min past the {time} start": "مضت {n} د على بداية الوردية ({time})",
    "{start} to {end}, left {n} min early": "من {start} إلى {end}، وانصراف مبكر {n} د",
    "{start} to {end}": "من {start} إلى {end}",
    "In at {time}, {n} min late": "الدخول {time}، تأخر {n} د",
    "In at {time}": "الدخول {time}",
    "Enter the date as 2026-08-31 and the time as 09:30.": "يُرجى كتابة التاريخ بهذا الشكل \u20662026-08-31\u2069 والوقت 09:30.",
    "The board cannot show a time in the future.": "لا يمكن للوحة عرض وقت في المستقبل.",
    # calendar of holidays and leave
    "Holidays and leave": "العطل الرسمية والإجازات",
    "Public holidays and approved leave": "العطل الرسمية والإجازات المعتمدة",
    "Neither counts as a working day. Saving a change recalculates the days affected.":
        "لا يُحتسب أيٌّ منهما يوم عمل. وحفظ أي تعديل يعيد احتساب الأيام المتأثرة.",
    "Add or rename a public holiday": "إضافة إجازة رسمية أو تعديل اسمها",
    "Name (English)": "الاسم (بالإنجليزية)",
    "Name (Arabic)": "الاسم (بالعربية)",
    "Save holiday": "حفظ الإجازة الرسمية",
    "Dates marked \"confirm\" are approximate because they follow the Hijri calendar. Check them against the "
    "official announcement.":
        "التواريخ المعلَّمة بـ«للتأكيد» تقريبية لأنها تتبع التقويم الهجري، ويُرجى مطابقتها مع الإعلان الرسمي.",
    "Public holidays": "الإجازات الرسمية",
    "confirm": "للتأكيد",
    "Remove": "حذف",
    "No public holidays recorded.": "لا توجد إجازات رسمية مسجلة.",
    "Recent leave": "أحدث الإجازات",
    "No leave recorded.": "لا توجد إجازات مسجلة.",
    "Record leave": "تسجيل إجازة",
    "Record approved leave": "تسجيل إجازة معتمدة",
    "To (inclusive)": "إلى (شاملًا)",
})

# ------------------------------------------------------------------ requests and approvals
AR.update({
    "Approvals": "الموافقات",
    "Requests from every department, including HR staff.": "طلبات جميع الأقسام، بما فيها طلبات موظفي الموارد البشرية.",
    "Requests from every department. Requests from HR staff go to the General Manager.":
        "طلبات جميع الأقسام. أما طلبات موظفي الموارد البشرية فتُرفع إلى المدير العام.",
    "Requests from the departments you manage.": "طلبات الأقسام التي تحت إدارتك.",
    "Your own requests are decided by someone else. Approving recalculates only the days involved.":
        "طلباتك الشخصية يبتّ فيها شخص آخر. والاعتماد يعيد احتساب الأيام المعنية فقط.",
    "Leave waiting for a decision": "إجازات بانتظار القرار",
    "Oldest request first": "الأقدم أولًا",
    "Days": "الأيام",
    "Requested": "تاريخ الطلب",
    "Decision": "القرار",
    "to {d}": "إلى {d}",
    "These days are waiting on this decision": "هذه الأيام معلّقة على هذا القرار",
    "Already started": "بدأت فعلًا",
    "Loaded from an HR file, not sent through the app": "حُمّلت من ملف الموارد البشرية، ولم تُرسل عبر النظام",
    "Imported": "مستوردة",
    "No leave requests are waiting.": "لا توجد طلبات إجازة بانتظار القرار.",
    "Missed-punch corrections": "تصحيحات البصمات المنسية",
    "The day as it stands now is shown, to help you judge the request": "تظهر حالة اليوم الحالية للمساعدة في تقدير الطلب",
    "Time given": "الوقت المذكور",
    "The day now": "حالة اليوم الآن",
    "Punches on record": "البصمات المسجلة",
    "Reason": "السبب",
    "No corrections are waiting.": "لا توجد تصحيحات بانتظار القرار.",
    "Recently decided leave": "إجازات بُتّ فيها مؤخرًا",
    "Nothing yet.": "لا شيء حتى الآن.",
    "Recently decided corrections": "تصحيحات بُتّ فيها مؤخرًا",
    "Punch": "البصمة",
    "By": "بواسطة",
    "Note (needed to reject)": "ملاحظة (مطلوبة عند الرفض)",
    "Note on the decision": "ملاحظة على القرار",
    "Approve": "اعتماد",
    "Reject": "رفض",
    # my requests
    "Request leave": "طلب إجازة",
    "(needed for \"other leave\")": "(مطلوب لنوع «إجازة أخرى»)",
    "Send leave request": "إرسال طلب الإجازة",
    "Up to {n} days in one request. Sick leave can be recorded afterwards, up to 90 days back.":
        "الحد الأقصى للطلب الواحد {n} يومًا. ويمكن تسجيل الإجازة المرضية بعد وقوعها بما لا يتجاوز 90 يومًا.",
    "Which punch was missed": "البصمة المنسية",
    "Clock-in (arriving)": "بصمة الدخول (عند الحضور)",
    "Clock-out (leaving)": "بصمة الخروج (عند الانصراف)",
    "The actual date and time": "التاريخ والوقت الفعليان",
    "For example: the badge reader at gate 2 was not working": "مثال: قارئ البطاقات عند البوابة 2 كان معطّلًا",
    "Send correction": "إرسال التصحيح",
    "For the last {n} days. Once approved, the punch is added by hand with the approver's name and that day is "
    "recalculated. A time outside your shift hours cannot be accepted, because it would not count towards any day.":
        "خلال آخر {n} يومًا. بعد الاعتماد تُضاف البصمة يدويًا باسم من اعتمدها، ويُعاد احتساب ذلك اليوم. "
        "ولا يُقبل وقت خارج ساعات ورديتك، لأنه لن يُحتسب لأي يوم.",
    "My leave requests": "طلبات إجازتي",
    "Newest first": "الأحدث أولًا",
    "HR record": "سجل الموارد البشرية",
    "No leave requests yet.": "لا توجد طلبات إجازة حتى الآن.",
    "My punch corrections": "تصحيحات بصماتي",
    "Withdraw": "سحب",
    "No corrections yet. If a day shows a missing punch or an absence by mistake, report it above.":
        "لا توجد تصحيحات حتى الآن. إذا ظهر يوم ببصمة ناقصة أو غياب عن طريق الخطأ، فيمكن الإبلاغ عنه أعلاه.",
    "As General Manager, your requests are recorded as approved straight away.":
        "بصفتك المدير العام، تُسجَّل طلباتك معتمدة مباشرة.",
    "Requests go to your department manager, to HR, or for HR staff to the General Manager. Your attendance only "
    "changes once a request is approved.":
        "تُرفع الطلبات إلى مدير القسم أو إلى الموارد البشرية، وطلبات موظفي الموارد البشرية إلى المدير العام. "
        "ولا يتغير سجل حضورك إلا بعد اعتماد الطلب.",
    # messages from the request pages
    "Missed punch ({kind}) at {time} reported for the shift of {date}. It will count once it is approved.":
        "تم الإبلاغ عن البصمة المنسية ({kind}) في {time} لوردية يوم {date}، وتُحتسب بعد اعتمادها.",
    "Only leave that is waiting for a decision, or approved leave that has not started yet, can be cancelled "
    "here. Please ask HR for anything else.":
        "لا يمكن الإلغاء من هنا إلا لإجازة بانتظار القرار أو لإجازة معتمدة لم تبدأ بعد. ولغير ذلك يُرجى "
        "التواصل مع الموارد البشرية.",
    "Leave request cancelled.": "أُلغي طلب الإجازة.",
    "That request had already changed.": "تغيّرت حالة هذا الطلب قبل ذلك.",
    "Missed punch report withdrawn.": "سُحب بلاغ البصمة المنسية.",
    "Only requests waiting for a decision can be withdrawn.": "لا يمكن سحب إلا الطلبات التي بانتظار القرار.",
    "Please add a short note when rejecting, so the employee knows why.":
        "يُرجى كتابة ملاحظة قصيرة عند الرفض ليعرف الموظف السبب.",
    "This cannot be approved because it overlaps approved leave from {start} to {end}.":
        "لا يمكن اعتماد هذا الطلب لأنه يتداخل مع إجازة معتمدة من {start} إلى {end}.",
    "That request has already been decided or withdrawn.": "سبق البتّ في هذا الطلب أو سحبه.",
    "Leave for {who} approved.": "اعتُمدت إجازة {who}.",
    "Leave for {who} rejected.": "رُفضت إجازة {who}.",
    "Approved for {who}: the {kind} at {time} has been added.": "اعتُمد طلب {who}: أُضيفت {kind} في {time}.",
    "The missed punch report from {who} was rejected.": "رُفض بلاغ البصمة المنسية المقدَّم من {who}.",
    "That request has already been decided.": "سبق البتّ في هذا الطلب.",
    "Approved automatically: this is the General Manager's own request.": "اعتُمد تلقائيًا: الطلب خاص بالمدير العام.",
    "You can only decide requests from people you are responsible for, and never your own.":
        "يقتصر البتّ على طلبات من هم ضمن مسؤوليتك، ولا يجوز البتّ في طلباتك الشخصية.",
    "This account is not linked to an employee record, so it cannot send requests.":
        "هذا الحساب غير مرتبط بسجل موظف، لذلك لا يمكن إرسال طلبات منه.",
    "Leave from {start} to {end} is recorded and approved.": "سُجّلت الإجازة من {start} إلى {end} واعتُمدت.",
    "Leave request sent for {start} to {end}. Your manager or HR will decide it.":
        "أُرسل طلب الإجازة من {start} إلى {end}، وسيبتّ فيه مديرك أو الموارد البشرية.",
    "The missed punch ({kind}) at {time} has been added to your record.":
        "أُضيفت البصمة المنسية ({kind}) في {time} إلى سجلك.",
    # validation of requests
    "These dates overlap another request: {kind} from {start} to {end} ({status}).":
        "تتداخل هذه التواريخ مع طلب آخر: {kind} من {start} إلى {end} ({status}).",
    "Choose whether the missed punch was a clock-in or a clock-out.": "يُرجى تحديد نوع البصمة المنسية: دخول أم خروج.",
    "Enter the date and time of the missed punch.": "يُرجى إدخال تاريخ البصمة المنسية ووقتها.",
    "Briefly explain what happened, in 5 to 500 characters (for example: the badge reader at gate 2 was not "
    "working).":
        "يُرجى شرح ما حدث باختصار، في 5 إلى 500 حرف (مثال: قارئ البطاقات عند البوابة 2 كان معطّلًا).",
    "The punch time is in the future.": "وقت البصمة في المستقبل.",
    "Missed punches can be reported for the last {n} days only.": "يمكن الإبلاغ عن البصمات المنسية خلال آخر {n} يومًا فقط.",
    "That time is not close to any of your shifts, so it would not count towards any day. Please check the date, "
    "or contact HR.":
        "هذا الوقت بعيد عن جميع ورديّاتك، فلن يُحتسب لأي يوم. يُرجى التحقق من التاريخ أو التواصل مع الموارد البشرية.",
    "A punch at {time} is already recorded around that time.": "توجد بصمة مسجلة في {time} قريبة من هذا الوقت.",
    "You have already reported this missed punch ({kind}) for {date}, and it is waiting for a decision.":
        "سبق الإبلاغ عن هذه البصمة المنسية ({kind}) ليوم {date}، وهي بانتظار القرار.",
    "This request has already been decided.": "سبق البتّ في هذا الطلب.",
    "The same punch has already been added.": "أُضيفت هذه البصمة نفسها من قبل.",
    "Attendance was recalculated from {start} to {end}.": "أُعيد احتساب الحضور من {start} إلى {end}.",
    "{label} is required.": "يلزم إدخال {label}.",
    "{label} is not a valid date.": "{label} ليس تاريخًا صحيحًا.",
    "The dates start before the joining date ({date}).": "تبدأ التواريخ قبل تاريخ الالتحاق ({date}).",
    "The dates run past the last day of employment ({date}).": "تمتد التواريخ إلى ما بعد آخر يوم عمل ({date}).",
    "Choose a leave type.": "يُرجى اختيار نوع الإجازة.",
    "Start date": "تاريخ البداية",
    "End date": "تاريخ النهاية",
    "Please give a short reason when the leave type is Other.": "يُرجى ذكر سبب مختصر عند اختيار «إجازة أخرى».",
    "The end date is before the start date.": "تاريخ النهاية يسبق تاريخ البداية.",
    "One request can cover at most {n} days. Please split longer leave into several requests.":
        "لا يتجاوز الطلب الواحد {n} يومًا. يُرجى تقسيم الإجازة الأطول على عدة طلبات.",
    "Leave can be requested up to {n} days after it started. For anything older, please contact HR.":
        "يمكن طلب الإجازة خلال {n} يومًا من بدايتها. وما كان أقدم من ذلك يُرجى التواصل فيه مع الموارد البشرية.",
    "Leave can be requested up to one year ahead.": "يمكن طلب الإجازة قبل موعدها بسنة واحدة على الأكثر.",
    # demo sentences stored in the data
    "Badge reader at the main gate was not responding": "قارئ البطاقات عند البوابة الرئيسية لم يكن يستجيب",
    "Forgot my badge at home, signed the visitor log": "نسيت بطاقتي في المنزل، ووقّعت في سجل الزوار",
    "Left through the warehouse exit which has no reader": "خرجت من باب المستودع، ولا يوجد عنده قارئ بطاقات",
    "Clock showed an error, security can confirm": "ظهرت رسالة خطأ على الجهاز، ويمكن للأمن التأكيد",
    "Family visit": "زيارة عائلية",
    "Consistently strong month.": "أداء قوي ومستقر طوال الشهر.",
    "Meets expectations.": "الأداء في مستوى التوقعات.",
    "Below expectations this month; follow-up conversation recommended.":
        "الأداء دون التوقعات هذا الشهر، ويُنصح بجلسة متابعة.",
})

# ------------------------------------------------------------------ evaluations and weights
AR.update({
    "Punctuality": "الانضباط في المواعيد",
    "Communication": "التواصل",
    "Task completion": "إنجاز المهام",
    "Teamwork": "العمل الجماعي",
    "Monthly evaluations": "التقييمات الشهرية",
    "{done} of {due} employees due an evaluation have one for {period} (an evaluation is due after working at "
    "least {days} days of the month). Nobody evaluates their own record.":
        "التقييمات المنجزة لشهر {period}: {done} من أصل {due} (يستحق الموظف التقييم إذا عمل {days} يومًا على "
        "الأقل من الشهر). ولا يقيّم أحد سجله بنفسه.",
    "Days employed": "أيام التوظيف",
    "Done": "منجز",
    "Not done yet": "لم يُنجز بعد",
    "Not due": "غير مستحق",
    "below {t}": "أقل من {t}",
    "No one you can see was employed in this month.": "لا يوجد ضمن نطاقك من كان على رأس العمل في هذا الشهر.",
    "Evaluate": "تقييم",
    "Score each area from 1 (well below expectations) to 5 (well above). The weight of each area for {period} is "
    "shown under its name; together they make 100%.":
        "تُعطى كل محور درجة من 1 (أقل بكثير من المتوقع) إلى 5 (أعلى بكثير من المتوقع). ويظهر وزن كل محور لشهر "
        "{period} تحت اسمه، ومجموع الأوزان 100%.",
    "weight {w}%": "الوزن {w}%",
    "1 well below · 3 as expected · 5 well above": "1 أقل بكثير · 3 كما هو متوقع · 5 أعلى بكثير",
    "Comments for the employee (optional, up to 2,000 characters)": "ملاحظات للموظف (اختيارية، حتى 2000 حرف)",
    "Describe the work you observed and the next steps you agreed. A score is one input to a conversation, not an "
    "automatic decision.":
        "يُرجى وصف العمل الملاحَظ والخطوات التالية المتفق عليها. فالدرجة مدخل من مدخلات الحوار، وليست قرارًا تلقائيًا.",
    "Save evaluation": "حفظ التقييم",
    "Cancel": "إلغاء",
    "Evaluation of {name} for {period}": "تقييم {name} لشهر {period}",
    "You are changing a saved evaluation; the earlier scores stay in its history.":
        "هذا تعديل على تقييم محفوظ، وتبقى الدرجات السابقة في سجله.",
    "No score weights apply to {period}. HR needs to set them first.":
        "لا توجد أوزان تقييم سارية لشهر {period}، ويجب أن تحددها الموارد البشرية أولًا.",
    "Evaluation history": "سجل التقييم",
    "current weighted score {s}": "الدرجة الموزونة الحالية {s}",
    "When": "الوقت",
    "Change": "التغيير",
    "Comments": "الملاحظات",
    "First saved": "الحفظ الأول",
    "Changed": "تعديل",
    "Weighted score": "الدرجة الموزونة",
    "No evaluations yet.": "لا توجد تقييمات حتى الآن.",
    "My evaluations": "تقييماتي",
    "Scores run from 1 (well below expectations) to 5 (well above). The weighted score uses the weights that "
    "applied when each evaluation was saved.":
        "الدرجات من 1 (أقل بكثير من المتوقع) إلى 5 (أعلى بكثير من المتوقع). وتُحسب الدرجة الموزونة بالأوزان التي "
        "كانت سارية عند حفظ كل تقييم.",
    "You can only see evaluations of people within your area.": "يقتصر اطلاعك على تقييمات من هم ضمن نطاقك.",
    "You cannot evaluate this person: they are outside your area, they are HR staff (evaluated by the General "
    "Manager), or it is your own record.":
        "لا يمكنك تقييم هذا الشخص: إما أنه خارج نطاقك، أو من موظفي الموارد البشرية (ويقيّمهم المدير العام)، "
        "أو أن السجل سجلك أنت.",
    "Evaluation updated. Weighted score: {s}.": "عُدّل التقييم. الدرجة الموزونة: {s}.",
    "Evaluation saved. Weighted score: {s}.": "حُفظ التقييم. الدرجة الموزونة: {s}.",
    "The employee had not joined yet in this month.": "لم يكن الموظف قد التحق بالعمل في هذا الشهر.",
    "The employee had already left before this month.": "كان الموظف قد ترك العمل قبل هذا الشهر.",
    "A month that has not started yet cannot be evaluated.": "لا يمكن تقييم شهر لم يبدأ بعد.",
    "You are not allowed to evaluate this employee.": "ليست لديك صلاحية تقييم هذا الموظف.",
    "Comments can be at most 2000 characters.": "لا تتجاوز الملاحظات 2000 حرف.",
    "No score weights are set for {period}. Please ask HR to set them.":
        "لا توجد أوزان تقييم لشهر {period}. يُرجى طلب تحديدها من الموارد البشرية.",
    "Enter a weight for {category}.": "يُرجى إدخال وزن محور {category}.",
    "The weight for {category} must be a number.": "يجب أن يكون وزن محور {category} رقمًا.",
    "The weight for {category} must be between 0 and 100.": "يجب أن يكون وزن محور {category} بين 0 و100.",
    "The weights must add up to 100% (they add up to {total}% now).": "يجب أن يكون مجموع الأوزان 100% (المجموع الآن {total}%).",
    "The score for {category} must be a whole number from 1 to 5.": "يجب أن تكون درجة محور {category} عددًا صحيحًا من 1 إلى 5.",
    "The score for {category} must be between 1 and 5.": "يجب أن تكون درجة محور {category} بين 1 و5.",
    # score weights
    "Score weights": "أوزان التقييم",
    "Each version applies from its first month until a newer version starts. Saved evaluations keep the version "
    "they were scored with, so changing the weights never rewrites past scores.":
        "يسري كل إصدار من شهره الأول حتى يبدأ إصدار أحدث. وتحتفظ التقييمات المحفوظة بالإصدار الذي احتُسبت به، "
        "فلا يغيّر تعديل الأوزان أي درجة سابقة.",
    "New version": "إصدار جديد",
    "Applies from": "يسري من",
    "Save weights": "حفظ الأوزان",
    "The four weights must add up to exactly 100.": "يجب أن يكون مجموع الأوزان الأربعة 100 تمامًا.",
    "Versions": "الإصدارات",
    "Saved by": "حفظه",
    "Saved on": "تاريخ الحفظ",
    "Initial setup": "الإعداد الأولي",
    "Weights saved. They apply to evaluations from {eff}; earlier evaluations keep the weights they were scored "
    "with.":
        "حُفظت الأوزان، وتسري على التقييمات ابتداءً من {eff}. أما التقييمات السابقة فتحتفظ بأوزانها.",
})

# ------------------------------------------------------------------ review and reports
AR.update({
    "Worth a conversation": "تستحق الحوار",
    "These flags point to where a supportive conversation may help. They are never a decision on their own and "
    "must not lead to automatic or disciplinary action.":
        "تشير هذه الملاحظات إلى حيث قد يفيد حوار داعم. وهي ليست قرارًا بذاتها، ولا يجوز أن يترتب عليها إجراء "
        "تلقائي أو تأديبي.",
    "Rule-based flags for {period}": "ملاحظات القواعد لشهر {period}",
    "Simple rules; every flag can be checked against the underlying numbers": "قواعد بسيطة، ويمكن التحقق من كل ملاحظة بالأرقام التي بُنيت عليها",
    "Rule": "القاعدة",
    "What it checks": "ما تتحقق منه",
    "What was found": "ما وُجد",
    "Nothing was flagged in {period} for the people you can see.": "لا توجد ملاحظات في {period} على من هم ضمن نطاقك.",
    "Trial: chance of a low score next month": "تجربة: احتمال انخفاض الدرجة في الشهر القادم",
    "Trial model": "نموذج تجريبي",
    "No model has been trained yet, so only the rules above are used.": "لم يُدرَّب أي نموذج بعد، لذلك تُستخدم القواعد أعلاه وحدها.",
    "No model is in use.": "لا يُستخدم أي نموذج.",
    "The rule-based flags above are the only review signal.": "ملاحظات القواعد أعلاه هي المؤشر الوحيد للمراجعة.",
    "A logistic regression trained on the months up to {last} and tested on {test} ({n} employee-months). At a "
    "0.5 cut-off it found {recall} of the real low scores, and {precision} of the people it flagged really scored "
    "low (F1 {f1}). A simple rule, \"scored low last month\", reached F1 {base}.":
        "نموذج انحدار لوجستي دُرّب على الأشهر حتى {last} واختُبر على {test} (عدد السجلات الشهرية: {n}). عند حدّ "
        "0.5 التقط {recall} من الدرجات المنخفضة الفعلية، وكانت درجات {precision} ممن أشار إليهم منخفضة فعلًا "
        "(F1 = {f1}). أما القاعدة البسيطة «كانت درجته منخفضة في الشهر الماضي» فبلغت F1 = {base}.",
    "It was trained on made-up data in which these patterns were built in on purpose, so the figures say nothing "
    "about real people.":
        "دُرّب على بيانات وهمية بُنيت فيها هذه الأنماط عمدًا، فلا تدل أرقامه على أشخاص حقيقيين.",
    "It only uses information available before the month it predicts, and never gender, age, nationality or "
    "department. A probability shows an association, not a cause.":
        "لا يستخدم إلا المعلومات المتاحة قبل الشهر الذي يتنبأ به، ولا يستخدم أبدًا الجنس أو العمر أو الجنسية أو "
        "القسم. والاحتمال يدل على ارتباط، لا على سبب.",
    "Based on": "بناءً على",
    "Predicting": "الشهر المتوقَّع",
    "Estimated chance": "الاحتمال التقديري",
    "The 25 highest among the people you can see, for {period}. Use it only to decide whom to check in with "
    "first.":
        "أعلى 25 احتمالًا بين من هم ضمن نطاقك لشهر {period}. ويُستعان به فقط لتحديد من يُبدأ بالتواصل معه.",
    "No estimates for the people you can see.": "لا توجد تقديرات لمن هم ضمن نطاقك.",
    "There are no evaluations in the database yet.": "لا توجد تقييمات في قاعدة البيانات بعد.",
    "There are not enough months of evaluations yet to train and test a model.":
        "لا توجد أشهر كافية من التقييمات لتدريب نموذج واختباره.",
    "There are too few low scores to train and test a model reliably.":
        "الدرجات المنخفضة أقل من أن يُدرَّب عليها نموذج ويُختبر بشكل موثوق.",
    "No model has been trained, so only the review rules are used.": "لم يُدرَّب أي نموذج، لذلك تُستخدم قواعد المراجعة وحدها.",
    # reports
    "Reports": "التقارير",
    "Monthly reports": "التقارير الشهرية",
    "Monthly PDF reports": "التقارير الشهرية بصيغة PDF",
    "One report for each month, scope and language. Asking for the same report again returns the saved copy "
    "unless you choose to replace it. Reports stay on this system; nothing is emailed.":
        "تقرير واحد لكل شهر ونطاق ولغة. وطلب التقرير نفسه مرة أخرى يعيد النسخة المحفوظة ما لم يُطلب استبدالها. "
        "تبقى التقارير داخل النظام، ولا يُرسل شيء بالبريد.",
    "Prepare a report": "إعداد تقرير",
    "Covering": "النطاق",
    "Language": "اللغة",
    "Replace an existing report": "استبدال تقرير موجود",
    "Prepare report": "إعداد التقرير",
    "A scheduled job can prepare last month's reports automatically; the same protection against duplicates "
    "applies.":
        "يمكن لمهمة مجدولة إعداد تقارير الشهر الماضي تلقائيًا، مع الحماية نفسها من التكرار.",
    "Requested by": "طلبه",
    "Started": "البدء",
    "Finished": "الانتهاء",
    "Download PDF": "تنزيل PDF",
    "Could not be prepared": "تعذّر الإعداد",
    "No reports yet. Prepare one above.": "لا توجد تقارير بعد. يمكن إعداد تقرير من الأعلى.",
    "The whole organisation": "المنشأة كاملة",
    "Scheduled job": "مهمة مجدولة",
    "Department managers can only prepare reports for the departments they manage.":
        "يقتصر مديرو الأقسام على إعداد تقارير الأقسام التي تحت إدارتهم.",
    "The report is ready.": "التقرير جاهز.",
    "This report already exists, so the saved copy is kept. Tick 'Replace an existing report' to prepare it again.":
        "هذا التقرير موجود، فأُبقيت النسخة المحفوظة. ولإعداده من جديد يُرجى تحديد «استبدال تقرير موجود».",
    "This report is already being prepared. Try again in a moment.": "هذا التقرير قيد الإعداد الآن. يُرجى المحاولة بعد قليل.",
    "The report could not be prepared. The details are in the server log.": "تعذّر إعداد التقرير، والتفاصيل في سجل الخادم.",
    "This report covers people outside your area.": "يشمل هذا التقرير أشخاصًا خارج نطاقك.",
})

# ------------------------------------------------------------------ the monthly PDF report
AR.update({
    "Attendance and Performance: Monthly Report": "تقرير الحضور والأداء الشهري",
    "{start} to {end} · {scope} · Prepared {when} · Calculation rules version {v}":
        "من {start} إلى {end} · {scope} · أُعدّ في {when} · إصدار قواعد الاحتساب {v}",
    "Made-up demonstration data. These figures show how the system works; they say nothing about any real "
    "organisation.":
        "بيانات تجريبية وهمية. توضح هذه الأرقام طريقة عمل النظام، ولا تدل على أي جهة حقيقية.",
    "What is counted: {month}, {scope}. Each employee is counted only on the days they were employed. Scores below "
    "{t} are flagged for review.":
        "نطاق الاحتساب: {month}، {scope}. يُحتسب كل موظف في أيام توظيفه فقط، ويُشار للمراجعة إلى كل درجة أقل من {t}.",
    "All departments": "جميع الأقسام",
    "None": "لا يوجد",
    "Attendance": "الحضور",
    "Measure": "المؤشر",
    "Value": "القيمة",
    "How it is worked out": "طريقة الاحتساب",
    "Employees with attendance records": "الموظفون الذين لهم سجلات حضور",
    "Everyone in scope who had at least one scheduled day": "كل من في النطاق وكان له يوم مجدول واحد على الأقل",
    "Attendance rate": "نسبة الحضور",
    "Days attended: {a} of {b} working days": "أيام الحضور: {a} من أصل {b} من أيام العمل",
    "Absence rate": "نسبة الغياب",
    "Days absent without approved leave: {n}": "أيام الغياب دون إجازة معتمدة: {n}",
    "Late rate": "نسبة التأخر",
    "Days late: {a}, out of {b} days attended": "أيام التأخر: {a}، من أصل أيام الحضور البالغة {b}",
    "Average lateness": "متوسط التأخر",
    "{n} min": "{n} د",
    "Minutes after the shift start, on late days only": "الدقائق بعد بداية الوردية، في أيام التأخر فقط",
    "Missing punches": "البصمات الناقصة",
    "Days with only one punch: {n}": "أيام ببصمة واحدة فقط: {n}",
    "Left early": "الانصراف المبكر",
    "Days the last punch came before the shift end, allowing for the grace period":
        "أيام جاءت فيها البصمة الأخيرة قبل نهاية الوردية بعد احتساب مدة السماح",
    "Average hours present": "متوسط ساعات التواجد",
    "First to last punch on full days; this is not confirmed working time":
        "من البصمة الأولى إلى الأخيرة في الأيام المكتملة، وليست ساعات عمل مؤكدة",
    "Leave and public holidays": "الإجازات والعطل الرسمية",
    "Days on approved leave / public holidays; not counted in the rates":
        "أيام الإجازات المعتمدة / العطل الرسمية، ولا تدخل في النِّسب",
    "Performance": "الأداء",
    "Evaluations saved": "التقييمات المحفوظة",
    "Employees who could be evaluated this month: {n}": "الموظفون المستحق تقييمهم هذا الشهر: {n}",
    "Evaluation coverage": "نسبة إنجاز التقييمات",
    "Counts employees who worked at least {n} days in the month": "تشمل من عمل {n} يومًا على الأقل من الشهر",
    "Average weighted score": "متوسط الدرجة الموزونة",
    "On a scale of 1 to 5, using the weights in force when each evaluation was saved":
        "على مقياس من 1 إلى 5، بالأوزان التي كانت سارية عند حفظ كل تقييم",
    "Below the review threshold": "أقل من حد المراجعة",
    "Weighted score below {t}": "درجة موزونة أقل من {t}",
    "Departments side by side": "مقارنة الأقسام",
    "Rates are calculated over working days, so large and small departments can be compared fairly. Departments "
    "with fewer than {n} employees are marked with * and their figures move a lot from month to month.":
        "تُحسب النِّسب على أيام العمل، فتمكن المقارنة العادلة بين الأقسام الكبيرة والصغيرة. والأقسام التي يقل "
        "عدد موظفيها عن {n} معلَّمة بـ * لأن أرقامها تتقلب كثيرًا من شهر إلى آخر.",
    "Department": "القسم",
    "Employees": "الموظفون",
    "Working days": "أيام العمل",
    "Absence": "الغياب",
    "Average score": "متوسط الدرجة",
    "Employees worth a conversation": "موظفون يستحق وضعهم الحوار",
    "These flags come from simple rules anyone can check, not from a prediction. They point to where a supportive "
    "conversation may help and must never be used on their own for a decision about a person.":
        "تأتي هذه الملاحظات من قواعد بسيطة يستطيع أي شخص التحقق منها، لا من توقعات. وهي تشير إلى حيث قد يفيد حوار "
        "داعم، ولا يجوز أن تُبنى عليها وحدها أي قرارات تخص الأشخاص.",
    "No rule was triggered this month.": "لم تنطبق أي قاعدة هذا الشهر.",
    "What was noticed": "الملاحظة",
    "Employee": "الموظف",
    "The numbers": "الأرقام",
    "{n} more are listed on the Review page of the app.": "باقي الملاحظات في صفحة المراجعة بالنظام: {n}.",
    "Data quality": "جودة البيانات",
    "Check": "الفحص",
    "Result": "النتيجة",
    "Punch files imported for this month": "ملفات البصمة المستوردة لهذا الشهر",
    "Rows set aside during import": "الصفوف المستبعدة أثناء الاستيراد",
    "Punches that did not match a working day": "بصمات لم تطابق أي يوم عمل",
    "Days whose shift had not finished when last calculated": "أيام لم تنتهِ ورديتها عند آخر احتساب",
    "Work on days off or public holidays (not counted in the rates)": "العمل في أيام الراحة أو العطل الرسمية (لا يدخل في النِّسب)",
    "Employees still waiting for an evaluation": "موظفون لم يُقيَّموا بعد",
    "Public holidays whose dates are estimates, not confirmed": "عطل رسمية تواريخها تقديرية وغير مؤكدة",
    "Definitions": "التعريفات",
    "Term": "المصطلح",
    "Meaning": "المعنى",
    "Working day": "يوم العمل",
    "A scheduled working day while the person is employed, not on approved leave or a public holiday, and whose "
    "shift has ended.":
        "يوم عمل مجدول خلال فترة التوظيف، ليس إجازة معتمدة ولا عطلة رسمية، وقد انتهت ورديته.",
    "Attended": "الحضور",
    "At least one punch on that day.": "بصمة واحدة على الأقل في ذلك اليوم.",
    "Late": "متأخر",
    "The first punch came after the shift start plus the grace period. A punch exactly at the end of the grace "
    "period is on time.":
        "جاءت البصمة الأولى بعد بداية الوردية ومدة السماح. والبصمة عند نهاية مدة السماح تمامًا تُعدّ في الموعد.",
    "Absent": "غائب",
    "A working day with no punch at all. This is decided only after the shift has ended.":
        "يوم عمل بلا أي بصمة، ولا يُحكم به إلا بعد انتهاء الوردية.",
    "Missing punch": "بصمة ناقصة",
    "Only one punch that day, so either the clock-in or the clock-out is missing.":
        "بصمة واحدة فقط في ذلك اليوم، فإما بصمة الدخول ناقصة وإما بصمة الخروج.",
    "Time from the first to the last punch. Breaks and unrecorded exits are unknown, so this is not confirmed "
    "working time.":
        "المدة من البصمة الأولى إلى الأخيرة. ولا تُعرف الاستراحات ولا مرات الخروج غير المسجلة، فهي ليست ساعات عمل مؤكدة.",
    "Night shift": "الوردية الليلية",
    "Counted on the date it starts.": "تُحتسب لليوم الذي تبدأ فيه.",
    "Each category score (1 to 5) multiplied by its weight, added up and divided by 100.":
        "تُضرب درجة كل محور (من 1 إلى 5) في وزنه، ثم تُجمع النتائج وتُقسم على 100.",
    "Made-up demo data, not real results": "بيانات تجريبية وهمية، وليست نتائج حقيقية",
    "Confidential: for HR use only": "سري: لاستخدام الموارد البشرية فقط",
    "Page {n}": "صفحة {n}",
    "Monthly attendance and performance report {period}": "تقرير الحضور والأداء الشهري {period}",
    "HR Analytics": "تحليلات الموارد البشرية",
    "Made-up demonstration data": "بيانات تجريبية وهمية",
    "Late rate (share of days attended)": "نسبة التأخر (من أيام الحضور)",
    "Review threshold {t}": "حد المراجعة {t}",
    "Weighted score (1 to 5)": "الدرجة الموزونة (من 1 إلى 5)",
})

# ------------------------------------------------------------------ records: employees, departments, shifts, audit
AR.update({
    "Activity log": "سجل النشاط",
    "The latest {n} actions: sign-ins, imports, recalculations, evaluations, changes to records, downloads and "
    "reports. Nothing here can be edited.":
        "أحدث الإجراءات (العدد: {n}): تسجيلات الدخول والاستيراد وإعادة الاحتساب والتقييمات وتعديل السجلات والتنزيلات "
        "والتقارير. ولا يمكن تعديل أي شيء هنا.",
    "Who": "المستخدم",
    "What happened": "ما حدث",
    "Record": "السجل",
    "Details": "التفاصيل",
    "Address": "عنوان الجهاز",
    "System": "النظام",
    # departments
    "Departments": "الأقسام",
    "A department's manager sees that department's data, both here and in Power BI.":
        "يطّلع مدير القسم على بيانات قسمه هنا وفي Power BI.",
    "Add department": "إضافة قسم",
    "Edit department": "تعديل قسم",
    "Code": "الرمز",
    "Manager": "المدير",
    "Current staff": "الموظفون الحاليون",
    "Active": "مفعّل",
    "Inactive": "غير مفعّل",
    "No manager": "دون مدير",
    "Save department": "حفظ القسم",
    "Choosing a manager gives that person's account the department manager role; removing them returns it to the "
    "employee role. HR and General Manager accounts are not changed.":
        "اختيار مدير يمنح حسابه دور مدير القسم، وإزالته تعيد الحساب إلى دور الموظف. ولا تتغير حسابات الموارد "
        "البشرية والمدير العام.",
    "The code can have 1 to 20 English letters, digits, '-' or '_'.":
        "يتكون الرمز من 1 إلى 20 خانة: حروف إنجليزية أو أرقام أو '-' أو '_'.",
    "The name must be 2 to 80 characters long.": "يجب أن يكون الاسم من 2 إلى 80 حرفًا.",
    "That manager was not found.": "لم يُعثر على هذا المدير.",
    "Another department already uses this code.": "هذا الرمز مستخدم لقسم آخر.",
    "Department saved. The manager's access changes straight away.": "حُفظ القسم، وتتغير صلاحيات المدير فورًا.",
    # employees
    "Name, code or badge": "الاسم أو الرقم الوظيفي أو البطاقة",
    "Current employees only": "الموظفون الحاليون فقط",
    "Job title": "المسمى الوظيفي",
    "Badge": "البطاقة",
    "Joined": "الالتحاق",
    "Left": "ترك العمل",
    "No employees match these filters.": "لا يوجد موظفون مطابقون لهذه الفلاتر.",
    "{n} you can see.": "ضمن نطاقك: {n}.",
    "Read only; HR keeps employee records up to date.": "للاطلاع فقط، وتتولى الموارد البشرية تحديث سجلات الموظفين.",
    "Import from CSV": "استيراد من ملف CSV",
    "Add employee": "إضافة موظف",
    "Time clock badge number": "رقم بطاقة جهاز الحضور",
    "Must match the badge number in the device files.": "يجب أن يطابق رقم البطاقة في ملفات الجهاز.",
    "Full name (English)": "الاسم الكامل (بالإنجليزية)",
    "Full name (Arabic)": "الاسم الكامل (بالعربية)",
    "Gender": "الجنس",
    "Not recorded": "غير مسجل",
    "Male": "ذكر",
    "Female": "أنثى",
    "Used only so that Arabic titles are written correctly. It is never used in scores or predictions.":
        "يُستخدم فقط لكتابة المسميات العربية بصيغتها الصحيحة، ولا يدخل أبدًا في الدرجات أو التوقعات.",
    "Work email": "البريد الإلكتروني للعمل",
    "Also the Power BI sign-in that decides which rows a person sees.":
        "وهو أيضًا حساب الدخول إلى Power BI الذي يحدد البيانات التي يراها الشخص.",
    "Job title (English)": "المسمى الوظيفي (بالإنجليزية)",
    "Job title (Arabic)": "المسمى الوظيفي (بالعربية)",
    "Edit {code}": "تعديل {code}",
    "Choose…": "اختيار…",
    "Last working day": "آخر يوم عمل",
    "Leave empty while the person works here. Days after it are never counted.":
        "يُترك فارغًا ما دام الشخص على رأس العمل، ولا تُحتسب أي أيام بعده.",
    "Shift starts on": "تبدأ الوردية في",
    "Only needed when the shift changes. New employees start on their start date.":
        "مطلوب فقط عند تغيير الوردية. ويبدأ الموظف الجديد من تاريخ التحاقه.",
    "Save employee": "حفظ بيانات الموظف",
    "Edit {name}": "تعديل بيانات {name}",
    "Changing the employment dates or the shift recalculates this employee's attendance for the days affected.":
        "تغيير تواريخ التوظيف أو الوردية يعيد احتساب حضور هذا الموظف في الأيام المتأثرة.",
    "The employee code can have 1 to 20 English letters, digits, '-' or '_'.":
        "يتكون الرقم الوظيفي من 1 إلى 20 خانة: حروف إنجليزية أو أرقام أو '-' أو '_'.",
    "The badge number can have 1 to 20 English letters, digits, '-' or '_'.":
        "يتكون رقم البطاقة من 1 إلى 20 خانة: حروف إنجليزية أو أرقام أو '-' أو '_'.",
    "The name must be 2 to 120 characters long.": "يجب أن يكون الاسم من 2 إلى 120 حرفًا.",
    "That email address does not look right.": "عنوان البريد الإلكتروني غير صحيح.",
    "Choose a department.": "يُرجى اختيار القسم.",
    "The start date": "تاريخ الالتحاق",
    "The last working day": "آخر يوم عمل",
    "The last working day cannot be before the start date.": "لا يمكن أن يسبق آخر يوم عمل تاريخ الالتحاق.",
    "Choose a shift.": "يُرجى اختيار الوردية.",
    "The shift start date": "تاريخ بداية الوردية",
    "Another employee already uses this code, badge number or email.":
        "الرقم الوظيفي أو رقم البطاقة أو البريد الإلكتروني مستخدم لموظف آخر.",
    "Employee saved.": "حُفظت بيانات الموظف.",
    "No employee has that code.": "لا يوجد موظف بهذا الرقم الوظيفي.",
    # shifts
    "Shifts": "الورديات",
    "A shift that ends earlier than it starts runs past midnight and belongs to the day it starts.":
        "الوردية التي تنتهي قبل وقت بدايتها تمتد إلى ما بعد منتصف الليل، وتُحتسب لليوم الذي تبدأ فيه.",
    "Add shift": "إضافة وردية",
    "Edit shift": "تعديل وردية",
    "Starts": "البداية",
    "Ends": "النهاية",
    "next day": "اليوم التالي",
    "Grace for lateness": "سماح التأخر",
    "Grace for leaving early": "سماح الانصراف المبكر",
    "Grace for lateness (minutes)": "سماح التأخر (بالدقائق)",
    "A first punch exactly at the start time plus the grace period still counts as on time.":
        "البصمة الأولى عند وقت البداية مضافًا إليه مدة السماح تمامًا تُعدّ في الموعد.",
    "Grace for leaving early (minutes)": "سماح الانصراف المبكر (بالدقائق)",
    "Save shift": "حفظ الوردية",
    "Changing the times affects any day that is recalculated later. To keep past results as they are, create a new "
    "shift and assign it to employees from a start date.":
        "تغيير الأوقات يؤثر في كل يوم يُعاد احتسابه لاحقًا. وللإبقاء على النتائج السابقة كما هي، يُنشأ وردية جديدة "
        "وتُسند إلى الموظفين ابتداءً من تاريخ محدد.",
    "The grace for lateness": "سماح التأخر",
    "The grace for leaving early": "سماح الانصراف المبكر",
    "{label} must be a whole number of minutes from 0 to 120.": "يجب أن تكون قيمة {label} عددًا صحيحًا من الدقائق بين 0 و120.",
    "The name is required.": "يلزم إدخال الاسم.",
    "Another shift already uses this code.": "هذا الرمز مستخدم لوردية أخرى.",
    "Shift saved. Days already calculated keep their results until they are recalculated (Import punches, then "
    "Recalculate).":
        "حُفظت الوردية. تبقى نتائج الأيام المحتسبة كما هي حتى يُعاد احتسابها (استيراد البصمات ثم إعادة الاحتساب).",
    # holidays and leave entered by HR
    "The date": "التاريخ",
    "The holiday name must be 2 to 80 characters long.": "يجب أن يكون اسم الإجازة الرسمية من 2 إلى 80 حرفًا.",
    "Public holiday saved.": "حُفظت الإجازة الرسمية.",
    "Public holiday removed.": "حُذفت الإجازة الرسمية.",
    "Choose a type of leave.": "يُرجى اختيار نوع الإجازة.",
    "The first day": "اليوم الأول",
    "The last day": "اليوم الأخير",
    "The last day is before the first day.": "اليوم الأخير يسبق اليوم الأول.",
    "One leave record can cover at most 180 days.": "لا يتجاوز سجل الإجازة الواحد 180 يومًا.",
    "These dates overlap leave from {a} to {b} for {code} that is {status}. Decide or cancel that request first "
    "(Approvals).":
        "تتداخل هذه التواريخ مع إجازة {code} من {a} إلى {b} (حالتها: {status}). يُرجى البتّ في ذلك الطلب أو إلغاؤه "
        "أولًا من صفحة الموافقات.",
    "Approved leave recorded for {code}.": "سُجّلت إجازة معتمدة لـ {code}.",
    "{label} must be a valid date.": "يجب أن يكون {label} تاريخًا صحيحًا.",
    "Attendance recalculated from {start} to {end}.": "أُعيد احتساب الحضور من {start} إلى {end}.",
})

# ------------------------------------------------------------------ imports and recalculation
AR.update({
    "Import punches": "استيراد البصمات",
    "Import time clock punches": "استيراد بصمات جهاز الحضور",
    "Upload a device file": "رفع ملف من الجهاز",
    "A CSV or Excel file with a badge column and a date-and-time column, for example 2026-08-03 07:58:12, or with a "
    "time zone such as 2026-08-03T04:58:12Z. Rows that cannot be used are set aside with the reason, and a punch "
    "that is already stored is never stored twice.":
        "ملف CSV أو Excel فيه عمود لرقم البطاقة وعمود للتاريخ والوقت، مثل \u20662026-08-03 07:58:12\u2069، أو مع منطقة زمنية "
        "مثل \u20662026-08-03T04:58:12Z\u2069. الصفوف غير الصالحة تُستبعد مع ذكر السبب، ولا تُحفظ البصمة نفسها مرتين أبدًا.",
    "File (.csv or .xlsx)": "الملف (.csv أو .xlsx)",
    "Time zone for times that do not state one": "المنطقة الزمنية للأوقات التي لا تذكر منطقتها",
    "Times that carry their own zone (such as Z or +03:00) are converted exactly; the rest are read in this zone.":
        "الأوقات التي تحمل منطقتها (مثل Z أو +03:00) تُحوَّل بدقة، وما عداها يُقرأ بهذه المنطقة.",
    "Device name (if the file has no device column)": "اسم الجهاز (إذا لم يكن في الملف عمود للجهاز)",
    "Import and calculate": "استيراد واحتساب",
    "Common column names are recognised, for example badge_id or Badge No, punch_time or Date Time, device_id or "
    "Terminal. The IN/OUT column is kept for reference only; results are worked out from the punch times.":
        "يتعرّف النظام على أسماء الأعمدة الشائعة، مثل badge_id أو Badge No، و punch_time أو Date Time، و device_id أو "
        "Terminal. ويُحفظ عمود IN/OUT للرجوع إليه فقط، فالنتائج تُحسب من أوقات البصمات.",
    "Recalculate a date range": "إعادة احتساب فترة",
    "Rebuilds the daily results from the stored punches, shifts, holidays and leave, for example after a shift was "
    "changed. Running it again gives the same result.":
        "تعيد بناء النتائج اليومية من البصمات والورديات والعطل والإجازات المحفوظة، كما بعد تعديل وردية مثلًا. "
        "وتكرار التشغيل يعطي النتيجة نفسها.",
    "Recalculate": "إعادة الاحتساب",
    "This refreshes the app only. Power BI reads the exported files and is refreshed separately.":
        "هذا يحدّث النظام فقط. أما Power BI فيقرأ الملفات المصدَّرة ويُحدَّث على حدة.",
    "Import history": "سجل الاستيراد",
    "All imports": "كل عمليات الاستيراد",
    "File": "الملف",
    "Rows": "الصفوف",
    "New punches": "بصمات جديدة",
    "Already stored": "محفوظة سابقًا",
    "Set aside": "مستبعدة",
    "No files imported yet. Upload a device file to begin.": "لم يُستورد أي ملف بعد. للبدء يُرجى رفع ملف من الجهاز.",
    "Import {n}": "عملية الاستيراد رقم {n}",
    "File type": "نوع الملف",
    "Time zone used": "المنطقة الزمنية المستخدمة",
    "Device": "الجهاز",
    "Taken from the file": "مأخوذ من الملف",
    "File fingerprint (SHA-256)": "بصمة الملف (SHA-256)",
    "Punches from – to": "البصمات من – إلى",
    "Rows set aside": "الصفوف المستبعدة",
    "Row": "الصف",
    "Values in the file": "القيم في الملف",
    "Fix these rows at the source (for example link the unknown badge to an employee) and import the corrected "
    "file; rows already stored are skipped automatically.":
        "تُصحَّح هذه الصفوف في المصدر (كربط البطاقة غير المعروفة بموظف) ثم يُستورد الملف المصحَّح، وتُتخطّى "
        "الصفوف المحفوظة سابقًا تلقائيًا.",
    "Every row in the file could be used.": "جميع صفوف الملف صالحة للاستخدام.",
    "{read} rows read: {new} new punches stored, {dup} already stored, {aside} set aside.":
        "الصفوف المقروءة: {read}؛ بصمات جديدة محفوظة: {new}؛ محفوظة سابقًا: {dup}؛ مستبعدة: {aside}.",
    "Choose a range of 1 to 400 days.": "يُرجى اختيار فترة من يوم واحد إلى 400 يوم.",
    "Recalculated {n} employee-days from {start} to {end}.":
        "أُعيد احتساب السجلات اليومية من {start} إلى {end} (عددها {n}).",
    "Choose a CSV or Excel file.": "يُرجى اختيار ملف CSV أو Excel.",
    "Only .csv and .xlsx files can be imported.": "لا يمكن استيراد إلا ملفات بصيغة csv أو xlsx.",
    "The time zone {tz} is not recognised.": "المنطقة الزمنية {tz} غير معروفة.",
    "This exact file was already imported (import {n}), so nothing was added.":
        "سبق استيراد هذا الملف نفسه (عملية الاستيراد رقم {n})، فلم يُضف شيء.",
    "The file could not be imported: {why}": "تعذّر استيراد الملف: {why}",
    "{new} new punches, {dup} already stored, {aside} set aside.":
        "بصمات جديدة: {new}، محفوظة سابقًا: {dup}، مستبعدة: {aside}.",
    "Imported: {summary} Attendance recalculated from {start} to {end}.":
        "تم الاستيراد: {summary} وأُعيد احتساب الحضور من {start} إلى {end}.",
    "{summary} There was nothing new to calculate.": "{summary} ولم يكن هناك جديد يُحتسب.",
    "Both dates are needed.": "يلزم إدخال التاريخين.",
})

# ------------------------------------------------------------------ accounts and bulk import
AR.update({
    "Who can sign in, and with which role. The department manager role follows the Departments page automatically.":
        "من يمكنه الدخول وبأي دور. ودور مدير القسم يتبع صفحة الأقسام تلقائيًا.",
    "As General Manager you can also give or remove HR access and manage HR accounts.":
        "وبصفتك المدير العام يمكنك أيضًا منح صلاحية الموارد البشرية وسحبها، وإدارة حساباتها.",
    "Only the General Manager can give or remove HR access, or change HR and General Manager accounts.":
        "منح صلاحية الموارد البشرية وسحبها وتعديل حسابات الموارد البشرية والمدير العام من اختصاص المدير العام وحده.",
    "Create an account": "إنشاء حساب",
    "Employee without an account ({n})": "موظفون بلا حساب ({n})",
    "(empty = the employee code)": "(إذا تُرك فارغًا = الرقم الوظيفي)",
    "Give HR access (the whole organisation)": "منح صلاحية الموارد البشرية (المنشأة كاملة)",
    "Create with a temporary password": "إنشاء بكلمة مرور مؤقتة",
    "Every current employee already has an account.": "لكل موظف حالي حساب بالفعل.",
    "Tidying up": "ترتيب الحسابات",
    "{n} still active although the employee has left.": "حسابات ما زالت مفعّلة مع أن أصحابها تركوا العمل: {n}.",
    "Switch off leavers' accounts": "إيقاف حسابات من تركوا العمل",
    "No active accounts belong to people who have left.": "لا توجد حسابات مفعّلة لأشخاص تركوا العمل.",
    "A switched-off account stops working on its next click, and its history is kept. Every change on this page is "
    "recorded in the activity log.":
        "يتوقف الحساب الموقوف عند أول نقرة تالية، ويُحتفظ بسجله. وكل تغيير في هذه الصفحة يُسجَّل في سجل النشاط.",
    "Username, name or code": "اسم المستخدم أو الاسم أو الرقم الوظيفي",
    "Role": "الدور",
    "Last sign-in": "آخر دخول",
    "Actions": "الإجراءات",
    "Not linked": "غير مرتبط",
    "Switched off": "موقوف",
    "Left {d}": "ترك العمل {d}",
    "Must choose a password": "يجب اختيار كلمة مرور",
    "Never": "لم يدخل بعد",
    "Reset password": "إعادة تعيين كلمة المرور",
    "Switch off": "إيقاف",
    "Switch on": "تفعيل",
    "Remove HR access": "سحب صلاحية الموارد البشرية",
    "Give HR access": "منح صلاحية الموارد البشرية",
    "You": "أنت",
    "General Manager only": "للمدير العام فقط",
    "No accounts match.": "لا توجد حسابات مطابقة.",
    "Choose an employee.": "يُرجى اختيار موظف.",
    "A username needs 3 to 40 characters: small English letters, digits, dots, dashes or underscores.":
        "يتكون اسم المستخدم من 3 إلى 40 خانة: حروف إنجليزية صغيرة أو أرقام أو نقاط أو شرطات.",
    "Only the General Manager can give HR access.": "منح صلاحية الموارد البشرية من اختصاص المدير العام وحده.",
    "That username is taken, or this employee already has an account.": "اسم المستخدم محجوز، أو أن لهذا الموظف حسابًا بالفعل.",
    "Only the General Manager can give or remove HR access.": "منح صلاحية الموارد البشرية وسحبها من اختصاص المدير العام وحده.",
    "The account {user} is switched on again.": "أُعيد تفعيل الحساب {user}.",
    "The account {user} is switched off.": "أُوقف الحساب {user}.",
    "The General Manager's role cannot be changed here.": "لا يمكن تغيير دور المدير العام من هنا.",
    "{user} now has the role: {role}.": "دور {user} الآن: {role}.",
    "Accounts switched off for people who have left: {n}.": "الحسابات الموقوفة لمن تركوا العمل: {n}.",
    "You cannot change your own account here. Use Password to change your password.":
        "لا يمكن تعديل حسابك الشخصي من هنا. ولتغيير كلمة المرور تُستخدم صفحة «كلمة المرور».",
    "Only the General Manager can change HR and General Manager accounts.":
        "تعديل حسابات الموارد البشرية والمدير العام من اختصاص المدير العام وحده.",
    "{user} is one of the public demo accounts, so it cannot be switched off, reset or changed. Try it on any other "
    "account.":
        "{user} من الحسابات التجريبية العامة، فلا يمكن إيقافه أو إعادة تعيينه أو تعديله. يمكن التجربة على أي حساب آخر.",
    # bulk employee import
    "Import employees": "استيراد الموظفين",
    "Add many people at once from a CSV file. Every row is checked first; then either every row is saved or none is.":
        "إضافة عدد كبير من الموظفين دفعة واحدة من ملف CSV. يُفحص كل صف أولًا، ثم تُحفظ الصفوف كلها أو لا يُحفظ شيء.",
    "Download a template": "تنزيل نموذج",
    "Upload": "رفع",
    "CSV file (UTF-8, with a header row)": "ملف CSV (بترميز UTF-8 وصف عناوين في أوله)",
    "Also create sign-in accounts": "إنشاء حسابات دخول أيضًا",
    "The username is the employee code in lower case. Temporary passwords are shown once and must be changed at "
    "the first sign-in.":
        "اسم المستخدم هو الرقم الوظيفي بحروف صغيرة. وتظهر كلمات المرور المؤقتة مرة واحدة، ويجب تغييرها عند أول دخول.",
    "Check only": "فحص فقط",
    "Check and import": "فحص واستيراد",
    "Columns": "الأعمدة",
    "department_code and shift_code must already exist (see Departments and Shifts).":
        "يجب أن يكون department_code و shift_code موجودَين مسبقًا (في صفحتي الأقسام والورديات).",
    "hire_date is written as YYYY-MM-DD, and the shift starts on that date.":
        "يُكتب hire_date بهذا الشكل \u20662026-08-31\u2069، وتبدأ الوردية من ذلك التاريخ.",
    "email, job_title and the Arabic columns (full_name_ar, job_title_ar) may be left empty; gender is M or F, or "
    "empty.":
        "يمكن ترك email و job_title والعمودين العربيين (full_name_ar و job_title_ar) فارغة. أما gender فقيمته M أو F أو فارغ.",
    "Only new employee codes are accepted. To change someone already on the system, use their Edit page.":
        "لا تُقبل إلا الأرقام الوظيفية الجديدة. ولتعديل موظف موجود تُستخدم صفحة التعديل الخاصة به.",
    "{n} need fixing in {file}. Nothing was saved.": "صفوف تحتاج إلى تصحيح في الملف {file}: {n}. لم يُحفظ شيء.",
    "and {n} more.": "وغيرها: {n}.",
    "Rows that passed": "الصفوف السليمة",
    "Ready to import": "جاهزة للاستيراد",
    "Choose the file again and press \"Check and import\".": "يُرجى اختيار الملف مرة أخرى ثم الضغط على «فحص واستيراد».",
    "Email": "البريد الإلكتروني",
    "These columns are missing: {cols}. Download the template to see the expected first row.":
        "هذه الأعمدة ناقصة: {cols}. يمكن تنزيل النموذج لمعرفة الصف الأول المطلوب.",
    "The file has no data rows.": "لا يحتوي الملف على صفوف بيانات.",
    "A file can have at most {n} rows.": "الحد الأقصى للملف {n} صف.",
    "the employee code must be 1 to 20 letters, digits, dashes or underscores":
        "الرقم الوظيفي يجب أن يكون من 1 إلى 20 خانة: حروف أو أرقام أو شرطات",
    "employee code {code} already exists (edit that employee instead)":
        "الرقم الوظيفي {code} موجود مسبقًا (يُعدَّل ذلك الموظف بدلًا من ذلك)",
    "employee code {code} appears twice in the file": "الرقم الوظيفي {code} مكرر في الملف",
    "the badge number must be 1 to 20 letters, digits, dashes or underscores":
        "رقم البطاقة يجب أن يكون من 1 إلى 20 خانة: حروف أو أرقام أو شرطات",
    "badge {badge} is already in use": "البطاقة {badge} مستخدمة مسبقًا",
    "the full name must be 2 to 120 characters": "الاسم الكامل يجب أن يكون من 2 إلى 120 حرفًا",
    "the Arabic name can be at most 120 characters": "الاسم العربي لا يتجاوز 120 حرفًا",
    "gender must be M, F or empty": "قيمة gender يجب أن تكون M أو F أو فارغة",
    "the email address is not valid": "البريد الإلكتروني غير صحيح",
    "the email {email} is already in use": "البريد الإلكتروني {email} مستخدم مسبقًا",
    "there is no department with the code '{code}'": "لا يوجد قسم بالرمز '{code}'",
    "there is no shift with the code '{code}'": "لا توجد وردية بالرمز '{code}'",
    "the joining date must look like 2026-08-31": "تاريخ الالتحاق يجب أن يُكتب بهذا الشكل \u20662026-08-31\u2069",
    "Row {n}: {problems}.": "الصف {n}: {problems}.",
    "Choose a CSV file.": "يُرجى اختيار ملف CSV.",
    "The file could not be read as CSV. Please save it from Excel as \"CSV UTF-8\" and try again.":
        "تعذّرت قراءة الملف بصيغة CSV. يُرجى حفظه من Excel بصيغة «CSV UTF-8» والمحاولة مرة أخرى.",
    "Nothing was imported because one of the values already exists. If you asked for login accounts, a username "
    "may already be taken.":
        "لم يُستورد شيء لأن إحدى القيم موجودة مسبقًا. وإذا طُلب إنشاء حسابات دخول، فربما يكون أحد أسماء المستخدمين محجوزًا.",
    "Imported {n}, each with a login account.": "تم استيراد {n}، مع إنشاء حساب دخول لكل منهم.",
    "Imported {n}.": "تم استيراد {n}.",
})
