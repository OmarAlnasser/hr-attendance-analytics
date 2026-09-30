# Windows Task Scheduler

Create two tasks (Task Scheduler > Create Task). In **General**, choose
"Run whether user is logged on or not". In **Actions**, use:

| Task | Trigger | Program | Arguments | Start in |
|---|---|---|---|---|
| HR nightly refresh | Daily 00:30 | `C:\hr-attendance-analytics\.venv\Scripts\python.exe` | `-m hr_analytics import-punches D:\TimeClock\Exports` | `C:\hr-attendance-analytics` |
| HR Power BI export | Daily 00:45 | same | `-m hr_analytics export-powerbi` | same |
| HR monthly reports | Monthly, day 3, 06:00 | same | `-m hr_analytics run-monthly --all-departments` | same |

Check the task history or `report_runs` (Monthly reports page) for the result. `run-monthly`
returns exit code 1 when a report fails, which Task Scheduler shows as "Last Run Result 0x1".
