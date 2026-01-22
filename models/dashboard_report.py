from odoo import models, fields, api
from datetime import datetime, timedelta, date



class DashboardReport(models.Model):
    _name = 'dashboard.report'
    _description = 'Dashboard Report'

    name = fields.Char('Report Name')
    report_date = fields.Date('Report Date', default=fields.Date.today)
    employee_id = fields.Many2one('hr.employee', 'Employee')
    department_id = fields.Many2one('hr.department', 'Department')
    employee_department_id = fields.Many2one('hr.department', 'Employee Department', related='employee_id.department_id', store=False)
    working_hours = fields.Float('Working Hours')
    report_type = fields.Selection([
        ('dwr', 'DWR'),
        ('sod', 'SOD'),
        ('pod', 'POD')
    ], string='Report Type')
    submitted_on = fields.Datetime('Submitted On')
    is_late = fields.Boolean('Submitted Late', compute='_compute_is_late', store=True)
    is_missed = fields.Boolean('Missed Report', compute='_compute_is_missed', store=True)
    manager_marks = fields.Integer('Manager Marks')
    tag = fields.Selection([
        ('red', 'Red'),
        ('blue', 'Blue'),
        ('green', 'Green')
    ], string='Tag', compute='_compute_tag', store=True)
    report_month = fields.Char('Report Month', compute='_compute_report_month', store=True)
    is_current_month = fields.Boolean('Is Current Month', compute='_compute_is_current_month', store=True)
    is_today = fields.Boolean('Is Today', compute='_compute_is_today', store=True)
    is_yesterday = fields.Boolean('Is Yesterday', compute='_compute_is_yesterday', store=True)


    # Data sync logic will be triggered by a scheduled action (cron) or manually after all modules are loaded.
    def sync_dashboard_data(self):
        """
        Sync data from daily_work_report and daily_tasks into dashboard.report.
        Performs incremental updates (upserts) instead of full deletion.
        """
        # Removed: self.env['dashboard.report'].search([]).unlink()

        # Sync from daily_work_report (employee.report and report)
        employee_reports = self.env['employee.report'].search([])
        for emp_rep in employee_reports:
            total_hours = 0.0
            for line in emp_rep.report_ids:
                if line.time_taken:
                    try:
                        h, m = map(int, line.time_taken.split(':'))
                        total_hours += h + m/60.0
                    except Exception:
                        pass
            
            # Upsert DWR record
            report_name = f"DWR {emp_rep.name.name if emp_rep.name else ''} {emp_rep.date}"
            vals = {
                'name': report_name,
                'report_date': emp_rep.date,
                'employee_id': emp_rep.name.id if emp_rep.name else False,
                'department_id': emp_rep.department_id.id if emp_rep.department_id else False,
                'working_hours': total_hours,
                'report_type': 'dwr',
                'submitted_on': False, # DWR in this module context seems to not track specific submission time for the report itself unless we add it, but existing logic had False. Keeping consistent but safe.
                # Actually, check if we can get submission time from somewhere? The other sync logic used False. 
                # Let's keep it as is for now to match original logic but just upsert.
                'is_late': False,
                'is_missed': False,
                'manager_marks': 0,
            }
            
            # Try to find existing record to update
            existing = self.env['dashboard.report'].search([
                ('report_type', '=', 'dwr'),
                ('employee_id', '=', vals['employee_id']),
                ('report_date', '=', vals['report_date'])
            ], limit=1)
            
            if existing:
                existing.write(vals)
            else:
                self.env['dashboard.report'].create(vals)

        # Sync from daily_tasks (daily.task)
        daily_tasks = self.env['daily.task'].search([])
        for task in daily_tasks:
            emp_name = task.employee_id.name if task.employee_id else ''
            emp_id = task.employee_id.id if task.employee_id else False
            dept_id = task.department_id.id if task.department_id else False
            
            # Upsert POD record
            try:
                pod_name = f"POD {emp_name} {task.date}"
                pod_vals = {
                    'name': pod_name,
                    'report_date': task.date,
                    'employee_id': emp_id,
                    'department_id': dept_id,
                    'working_hours': 0.0,
                    'report_type': 'pod',
                    'submitted_on': task.pod_submitted_date if getattr(task, 'pod_submitted', False) else False,
                    'is_late': False, # Computed field will handle logic if triggered, but here we set initial
                    'is_missed': not getattr(task, 'pod_submitted', False),
                    'manager_marks': 0,
                }
                
                existing_pod = self.env['dashboard.report'].search([
                    ('report_type', '=', 'pod'),
                    ('employee_id', '=', emp_id),
                    ('report_date', '=', task.date)
                ], limit=1)
                
                if existing_pod:
                    existing_pod.write(pod_vals)
                else:
                    self.env['dashboard.report'].create(pod_vals)
            except Exception:
                pass

            # Upsert SOD record
            # Consider SOD submitted when state == 'done' or sod_description present
            sod_submitted = False
            if getattr(task, 'state', False) == 'done':
                sod_submitted = True
            if getattr(task, 'sod_description', False):
                sod_submitted = True
            
            try:
                sod_name = f"SOD {emp_name} {task.date}"
                sod_vals = {
                    'name': sod_name,
                    'report_date': task.date,
                    'employee_id': emp_id,
                    'department_id': dept_id,
                    'working_hours': 0.0,
                    'report_type': 'sod',
                    'submitted_on': fields.Datetime.now() if sod_submitted else False, # Note: using now() for sync might be inaccurate if repeated. Ideally should be stored on task. Assuming acceptable for now.
                    'is_late': False,
                    'is_missed': False, # logic handled by computed
                    'manager_marks': 0,
                }
                # Fix: Don't overwrite submitted_on with now() if it's already set? 
                # The original logic used fields.Datetime.now() if sod_submitted. 
                # Only strictly correct if we captured that time previously.
                # For upsert, if we already have a record and it has submitted_on, we might want to keep it?
                # But original logic had no history, so it always reset. 
                # Let's keep original behavior for now but wrapped in upsert.
                
                existing_sod = self.env['dashboard.report'].search([
                    ('report_type', '=', 'sod'),
                    ('employee_id', '=', emp_id),
                    ('report_date', '=', task.date)
                ], limit=1)
                
                if existing_sod:
                    # If already submitted, don't update submitted_on with now() to avoid shifting time?
                    # Original logic: always now() if submitted.
                    # We should probably respect existing if it exists.
                    if existing_sod.submitted_on:
                        sod_vals['submitted_on'] = existing_sod.submitted_on
                    existing_sod.write(sod_vals)
                else:
                    self.env['dashboard.report'].create(sod_vals)
            except Exception:
                pass


        # Rebuild missed reports after dashboard data sync
        try:
            self.env['dashboard.missed.report'].sudo().sync_missed_reports()
        except Exception:
            # Don't block sync if missed report rebuild fails
            _ = None

        # Also sync monthly employee and department summary after dashboard sync
        try:
            self.env['dashboard.employee.monthly'].sudo().sync_employee_monthly()
        except Exception:
            # Don't block sync if monthly summary fails
            _ = None
        try:
            self.env['dashboard.department.monthly'].sudo().sync_department_monthly()
        except Exception:
            # Don't block sync if department monthly summary fails
            _ = None

        # Also sync monthly employee summary after dashboard sync
        try:
            self.env['dashboard.employee.monthly'].sudo().sync_employee_monthly()
        except Exception:
            # Don't block sync if monthly summary fails
            _ = None

    @api.model
    def regenerate_pod_sod_from_tasks(self, start_date=None, end_date=None):
        """One-time helper: delete and recreate POD/SOD `dashboard.report` rows from `daily.task`.

        start_date/end_date: optional strings 'YYYY-MM-DD' to limit range. If omitted, uses current month-to-date.
        Returns a dict with counts: {'removed': N, 'created': M}
        """
        today_str = fields.Date.context_today(self)
        try:
            today = fields.Date.from_string(today_str)
        except Exception:
            today = date.today()

        if start_date:
            start = fields.Date.from_string(start_date) if isinstance(start_date, str) else start_date
        else:
            start = date(today.year, today.month, 1)

        if end_date:
            end = fields.Date.from_string(end_date) if isinstance(end_date, str) else end_date
        else:
            end = today

        start_str = fields.Date.to_string(start)
        end_str = fields.Date.to_string(end)

        # Remove existing POD/SOD dashboard.report rows in the range
        to_remove = self.env['dashboard.report'].sudo().search([
            ('report_type', 'in', ('pod', 'sod')),
            ('report_date', '>=', start_str),
            ('report_date', '<=', end_str),
        ])
        removed = len(to_remove)
        if to_remove:
            to_remove.unlink()

        # Recreate from daily.task
        tasks = self.env['daily.task'].sudo().search([('date', '>=', start_str), ('date', '<=', end_str)])
        created = 0
        for t in tasks:
            emp = t.employee_id.id if t.employee_id else False
            dept = t.department_id.id if t.department_id else False
            # POD
            pod_sub = bool(getattr(t, 'pod_submitted', False))
            pod_dt = getattr(t, 'pod_submitted_date', False) or (fields.Datetime.now() if pod_sub else False)
            try:
                self.env['dashboard.report'].sudo().create({
                    'name': f"POD {t.employee_id.name if t.employee_id else ''} {t.date}",
                    'report_date': t.date,
                    'employee_id': emp,
                    'department_id': dept,
                    'working_hours': 0.0,
                    'report_type': 'pod',
                    'submitted_on': pod_dt,
                    'is_late': False,
                    'manager_marks': 0,
                })
            except Exception:
                pass

            # SOD: submitted when state == 'done' or sod_description present
            sod_sub = (getattr(t, 'state', False) == 'done') or bool(getattr(t, 'sod_description', False))
            sod_dt = fields.Datetime.now() if sod_sub else False
            try:
                self.env['dashboard.report'].sudo().create({
                    'name': f"SOD {t.employee_id.name if t.employee_id else ''} {t.date}",
                    'report_date': t.date,
                    'employee_id': emp,
                    'department_id': dept,
                    'working_hours': 0.0,
                    'report_type': 'sod',
                    'submitted_on': sod_dt,
                    'is_late': False,
                    'manager_marks': 0,
                })
            except Exception:
                pass

            created += 1

        # Rebuild missed reports
        try:
            self.env['dashboard.missed.report'].sudo().sync_missed_reports()
        except Exception:
            pass

        return {'removed': removed, 'created': created}

    @api.depends('submitted_on', 'report_type', 'report_date')
    def _compute_is_late(self):
        for rec in self:
            if not rec.submitted_on:
                rec.is_late = False
                continue
            if rec.report_type in ['dwr', 'sod']:
                deadline = datetime.combine(rec.report_date, datetime.strptime('23:59:59', '%H:%M:%S').time())
            elif rec.report_type == 'pod':
                deadline = datetime.combine(rec.report_date, datetime.strptime('10:00:00', '%H:%M:%S').time())
            else:
                deadline = None
            rec.is_late = rec.submitted_on > deadline if deadline else False

    @api.depends('submitted_on')
    def _compute_is_missed(self):
        for rec in self:
            rec.is_missed = not rec.submitted_on

    @api.depends('working_hours')
    def _compute_tag(self):
        for rec in self:
            if rec.working_hours < 8:
                rec.tag = 'red'
            elif rec.working_hours > 10:
                rec.tag = 'green'
            else:
                rec.tag = 'blue'

    @api.depends('report_date')
    def _compute_report_month(self):
        for rec in self:
            if rec.report_date:
                try:
                    d = fields.Date.from_string(rec.report_date)
                    rec.report_month = f"{d.year:04d}-{d.month:02d}"
                except Exception:
                    rec.report_month = False
            else:
                rec.report_month = False

    @api.depends('report_date')
    def _compute_is_current_month(self):
        # Use context-aware today
        today_str = fields.Date.context_today(self)
        try:
            today = fields.Date.from_string(today_str)
        except Exception:
            today = None
        for rec in self:
            if not rec.report_date or not today:
                rec.is_current_month = False
                continue
            try:
                d = fields.Date.from_string(rec.report_date)
                rec.is_current_month = (d.year == today.year and d.month == today.month)
            except Exception:
                rec.is_current_month = False

    @api.depends('report_date')
    def _compute_is_today(self):
        today_str = fields.Date.context_today(self)
        try:
            today = fields.Date.from_string(today_str)
        except Exception:
            today = None
        for rec in self:
            if not rec.report_date or not today:
                rec.is_today = False
                continue
            try:
                d = fields.Date.from_string(rec.report_date)
                rec.is_today = (d == today)
            except Exception:
                rec.is_today = False

    @api.depends('report_date')
    def _compute_is_yesterday(self):
        today_str = fields.Date.context_today(self)
        try:
            today = fields.Date.from_string(today_str)
        except Exception:
            today = None
        if today:
            yesterday = today - timedelta(days=1)
        else:
            yesterday = None
        for rec in self:
            if not rec.report_date or not yesterday:
                rec.is_yesterday = False
                continue
            try:
                d = fields.Date.from_string(rec.report_date)
                rec.is_yesterday = (d == yesterday)
            except Exception:
                rec.is_yesterday = False


class MissedReport(models.Model):
    _name = 'dashboard.missed.report'
    _description = 'Missed Reports per Employee'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    department_id = fields.Many2one('hr.department', string='Department')
    missed_pod = fields.Integer('Missed PODs', default=0)
    missed_sod = fields.Integer('Missed SODs', default=0)
    missed_dwr = fields.Integer('Missed DWRs', default=0)
    total_missed = fields.Integer('Total Missed', compute='_compute_total', store=True)
    total_working_days = fields.Integer('Total Working Days', default=0)
    pod_submitted_count = fields.Integer('POD Submitted', default=0)
    sod_submitted_count = fields.Integer('SOD Submitted', default=0)
    dwr_submitted_count = fields.Integer('DWR Submitted', default=0)
    has_missed_current_month = fields.Boolean('Has Missed This Month', compute='_compute_missed_flags', store=True)
    has_missed_today = fields.Boolean('Has Missed Today', compute='_compute_missed_flags', store=True)
    has_missed_yesterday = fields.Boolean('Has Missed Yesterday', compute='_compute_missed_flags', store=True)
    has_tag_red = fields.Boolean('Has Missed with Red Tag', compute='_compute_missed_flags', store=True)
    has_tag_blue = fields.Boolean('Has Missed with Blue Tag', compute='_compute_missed_flags', store=True)
    has_tag_green = fields.Boolean('Has Missed with Green Tag', compute='_compute_missed_flags', store=True)

    @api.depends('missed_pod', 'missed_sod', 'missed_dwr')
    def _compute_total(self):
        for rec in self:
            rec.total_missed = (rec.missed_pod or 0) + (rec.missed_sod or 0) + (rec.missed_dwr or 0)

    @api.model
    def sync_missed_reports(self):
        """Rebuild missed report records from dashboard.report data."""
        # Removed full delete: existing = self.search([]); if existing: existing.unlink()

        # Count only from first day of current month up to today (inclusive)
        today_str = fields.Date.context_today(self)
        try:
            today_dt = fields.Date.from_string(today_str)
        except Exception:
            today_dt = None

        if today_dt:
            month_start = date(today_dt.year, today_dt.month, 1)
            start_str = fields.Date.to_string(month_start)
            end_str = fields.Date.to_string(today_dt)
        else:
            # fallback to no date restriction
            start_str = False
            end_str = False

        employees = self.env['hr.employee'].search([('active', '=', True)])
        for emp in employees:
            # compute working days from month_start to today (exclude Sundays)
            working_days = 0
            if today_dt:
                cur = month_start
                while cur <= today_dt:
                    if cur.weekday() != 6:
                        working_days += 1
                    cur = cur + timedelta(days=1)

            # Date ranges for tasks and DWR
            task_domain = []
            dwr_domain = []
            if start_str and end_str:
                task_domain = [('date', '>=', start_str), ('date', '<=', end_str)]
                dwr_domain = [('date', '>=', start_str), ('date', '<=', end_str)]

            # POD submitted: count daily.task with pod_submitted True
            pod_submitted = self.env['daily.task'].search_count([
                ('employee_id', '=', emp.id), ('pod_submitted', '=', True)
            ] + task_domain)

            # SOD submitted: fetch tasks and count where state == 'done' or sod_description present
            tasks = self.env['daily.task'].search([('employee_id', '=', emp.id)] + task_domain)
            sod_submitted = sum(1 for t in tasks if (getattr(t, 'state', False) == 'done') or bool(getattr(t, 'sod_description', False)))

            # DWR submitted: use employee.report (dwr module) where submitted_time is set
            dwr_submitted = self.env['employee.report'].search_count([
                ('name', '=', emp.id), ('submitted_time', '!=', False)
            ] + dwr_domain)

            # Compute missed as working_days - submitted (capped at 0)
            missed_pod = working_days - pod_submitted if working_days and (working_days - pod_submitted) > 0 else 0
            missed_sod = working_days - sod_submitted if working_days and (working_days - sod_submitted) > 0 else 0
            missed_dwr = working_days - dwr_submitted if working_days and (working_days - dwr_submitted) > 0 else 0

            # Create or update missed report for the employee
            vals = {
                'employee_id': emp.id,
                'department_id': emp.department_id.id if emp.department_id else False,
                'total_working_days': working_days,
                'pod_submitted_count': pod_submitted,
                'sod_submitted_count': sod_submitted,
                'dwr_submitted_count': dwr_submitted,
                'missed_pod': missed_pod,
                'missed_sod': missed_sod,
                'missed_dwr': missed_dwr,
            }
            existing = self.search([('employee_id', '=', emp.id)], limit=1)
            if existing:
                existing.write(vals)
            else:
                self.create(vals)

        return True

    @api.depends('missed_pod', 'missed_sod', 'missed_dwr')
    def _compute_missed_flags(self):
        """Compute boolean flags by querying dashboard.report for this employee."""
        for rec in self:
            emp_id = rec.employee_id.id if rec.employee_id else False
            if not emp_id:
                rec.has_missed_current_month = False
                rec.has_missed_today = False
                rec.has_missed_yesterday = False
                rec.has_tag_red = False
                rec.has_tag_blue = False
                rec.has_tag_green = False
                continue
            # current month
            rec.has_missed_current_month = self.env['dashboard.report'].search_count([
                ('employee_id', '=', emp_id), ('is_missed', '=', True), ('is_current_month', '=', True)
            ]) > 0
            # today
            rec.has_missed_today = self.env['dashboard.report'].search_count([
                ('employee_id', '=', emp_id), ('is_missed', '=', True), ('is_today', '=', True)
            ]) > 0
            # yesterday
            rec.has_missed_yesterday = self.env['dashboard.report'].search_count([
                ('employee_id', '=', emp_id), ('is_missed', '=', True), ('is_yesterday', '=', True)
            ]) > 0
            # tag flags (any missed with that tag)
            rec.has_tag_red = self.env['dashboard.report'].search_count([
                ('employee_id', '=', emp_id), ('is_missed', '=', True), ('tag', '=', 'red')
            ]) > 0
            rec.has_tag_blue = self.env['dashboard.report'].search_count([
                ('employee_id', '=', emp_id), ('is_missed', '=', True), ('tag', '=', 'blue')
            ]) > 0
            rec.has_tag_green = self.env['dashboard.report'].search_count([
                ('employee_id', '=', emp_id), ('is_missed', '=', True), ('tag', '=', 'green')
            ]) > 0


class EmployeeMonthly(models.Model):
    _name = 'dashboard.employee.monthly'
    _description = 'Dashboard Employee Monthly Totals'
    _rec_name = 'employee_id'

    employee_id = fields.Many2one('hr.employee', string='Employee', required=True)
    department_id = fields.Many2one('hr.department', string='Department')
    report_month = fields.Char(string='Report Month', help='YYYY-MM')
    total_work_minutes = fields.Integer(string='Total Work Minutes', default=0)
    working_hours = fields.Float(string='Working Hours', digits=(16,2), default=0.0)

    @api.model
    def sync_employee_monthly(self, year=None, month=None):
        """Populate dashboard.employee.monthly for the given month (defaults to current month-to-date).

        This sums `total_work_minutes` from `employee.report` where `submitted_time` is set.
        """
        today = fields.Date.context_today(self)
        try:
            today_dt = fields.Date.from_string(today)
        except Exception:
            today_dt = date.today()

        if year and month:
            start = date(int(year), int(month), 1)
            # end of month or today if same month
            if start.year == today_dt.year and start.month == today_dt.month:
                end = today_dt
            else:
                # compute last day of month
                from calendar import monthrange
                last_day = monthrange(start.year, start.month)[1]
                end = date(start.year, start.month, last_day)
        else:
            start = date(today_dt.year, today_dt.month, 1)
            end = today_dt

        start_str = fields.Date.to_string(start)
        end_str = fields.Date.to_string(end)

        # Build map employee -> total minutes
        employees = self.env['hr.employee'].search([('active', '=', True)])
        for emp in employees:
            domain = [
                ('name', '=', emp.id),
                ('submitted_time', '!=', False),
                ('date', '>=', start_str),
                ('date', '<=', end_str),
            ]
            reports = self.env['employee.report'].search(domain)
            total_minutes = sum((r.total_work_minutes or 0) for r in reports)
            hours = round(total_minutes / 60.0, 2) if total_minutes else 0.0

            vals = {
                'employee_id': emp.id,
                'department_id': emp.department_id.id if emp.department_id else False,
                'report_month': f"{start.year:04d}-{start.month:02d}",
                'total_work_minutes': total_minutes,
                'working_hours': hours,
            }
            rec = self.search([('employee_id', '=', emp.id), ('report_month', '=', vals['report_month'])], limit=1)
            if rec:
                rec.write(vals)
            else:
                self.create(vals)

        return True


class DepartmentMonthly(models.Model):
    _name = 'dashboard.department.monthly'
    _description = 'Dashboard Department Monthly Totals'
    _rec_name = 'department_id'

    department_id = fields.Many2one('hr.department', string='Department', required=True)
    report_month = fields.Char(string='Report Month', help='YYYY-MM')
    total_work_minutes = fields.Integer(string='Total Work Minutes', default=0)
    working_hours = fields.Float(string='Working Hours', digits=(16,2), default=0.0)
    employee_ids = fields.One2many(
        'dashboard.employee.monthly',
        'department_id',
        string='Employees'
    )

    @api.model
    def sync_department_monthly(self, year=None, month=None):
        """Populate dashboard.department.monthly for the given month (defaults to current month-to-date).

        Summation is taken from `employee.report` records with `submitted_time` set.
        """
        today = fields.Date.context_today(self)
        try:
            today_dt = fields.Date.from_string(today)
        except Exception:
            today_dt = date.today()

        if year and month:
            start = date(int(year), int(month), 1)
            if start.year == today_dt.year and start.month == today_dt.month:
                end = today_dt
            else:
                from calendar import monthrange
                last_day = monthrange(start.year, start.month)[1]
                end = date(start.year, start.month, last_day)
        else:
            start = date(today_dt.year, today_dt.month, 1)
            end = today_dt

        start_str = fields.Date.to_string(start)
        end_str = fields.Date.to_string(end)

        # aggregate working hours by department from dashboard.employee.monthly
        # aggregate department monthly data from dashboard.report (DWR only, current month)
        today = fields.Date.context_today(self)
        try:
            today_dt = fields.Date.from_string(today)
        except Exception:
            today_dt = date.today()
        start = date(today_dt.year, today_dt.month, 1)
        end = today_dt
        start_str = fields.Date.to_string(start)
        end_str = fields.Date.to_string(end)
        domain = [
            ('report_type', '=', 'dwr'),
            ('report_date', '>=', start_str),
            ('report_date', '<=', end_str),
        ]
        reports = self.env['dashboard.report'].search(domain)
        dept_hours = {}
        for r in reports:
            dept_id = r.department_id.id if r.department_id else None
            if dept_id:
                dept_hours.setdefault(dept_id, 0.0)
                dept_hours[dept_id] += r.working_hours or 0.0
        month_str = f"{start.year:04d}-{start.month:02d}"
        for dept_id, hours in dept_hours.items():
            vals = {
                'department_id': dept_id,
                'report_month': month_str,
                'total_work_minutes': int(hours * 60),
                'working_hours': round(hours, 2),
            }
            rec = self.search([('department_id', '=', dept_id), ('report_month', '=', month_str)], limit=1)
            if rec:
                rec.write(vals)
            else:
                self.create(vals)

        return True
