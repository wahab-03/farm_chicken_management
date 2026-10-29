from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class VaccineVaccine(models.Model):
    _name = 'vaccine.vaccine'
    _description = 'Vaccine Master'
    _order = 'name'

    name = fields.Char(string='Vaccine Name', required=True)
    purchase_ids = fields.One2many('vaccine.purchase', 'vaccine_id', string='Purchase History')
    current_stock = fields.Float(string='Current Stock', compute='_compute_stock')
    total_used = fields.Float(string='Total Used', compute='_compute_stock')
    latest_expiry_date = fields.Date(string='Nearest Expiry Date', compute='_compute_stock')
    note = fields.Text(string='Note')

    @api.depends('purchase_ids.quantity', 'purchase_ids.expiry_date')
    def _compute_stock(self):
        Schedule = self.env['vaccine.batch.schedule']
        for vac in self:
            purchased = sum(vac.purchase_ids.mapped('quantity'))
            used = sum(Schedule.search([('vaccine_id', '=', vac.id), ('state', '=', 'done')]).mapped('quantity_used'))
            vac.total_used = used
            vac.current_stock = purchased - used
            expiries = vac.purchase_ids.filtered('expiry_date').mapped('expiry_date')
            vac.latest_expiry_date = min(expiries) if expiries else False


class VaccinePurchase(models.Model):
    _name = 'vaccine.purchase'
    _description = 'Vaccine Purchase / Stock-In'
    _order = 'purchase_date desc'

    vaccine_id = fields.Many2one('vaccine.vaccine', string='Vaccine', required=True, ondelete='cascade')
    purchase_date = fields.Date(string='Purchase Date', default=fields.Date.context_today, required=True)
    quantity = fields.Float(string='Quantity Purchased', required=True)
    purchase_price = fields.Float(string='Purchase Price')
    expiry_date = fields.Date(string='Expiry Date')
    supplier_id = fields.Many2one('res.partner', string='Supplier')

    @api.constrains('quantity', 'purchase_price', 'expiry_date')
    def _check_values(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError('Vaccine purchase quantity must be greater than zero.')
            if rec.purchase_price < 0:
                raise ValidationError('Purchase price cannot be negative.')
            if rec.expiry_date and rec.expiry_date < rec.purchase_date:
                raise ValidationError('Expiry Date cannot be before Purchase Date.')


class VaccineSchedule(models.Model):
    _name = 'vaccine.schedule'
    _description = 'Vaccine Schedule Template (Age-wise)'
    _order = 'age_days'

    name = fields.Char(string='Schedule Name', compute='_compute_name', store=True)
    vaccine_id = fields.Many2one('vaccine.vaccine', string='Vaccine', required=True)
    age_days = fields.Integer(string='Due at Age (Days)', required=True)
    age_label = fields.Char(string='Age Label (e.g. 2 Month)')
    applicable_chicken_type = fields.Selection([
        ('all', 'All Types'),
        ('deshi', 'Deshi'),
        ('farmer_poultry', 'Farmer / Poultry'),
        ('pahari', 'Pahari'),
    ], string='Applicable Chicken Type', default='all', required=True)
    note = fields.Text(string='Note')
    preview_due_date = fields.Date(
        string='Preview Due Date (from today)',
        compute='_compute_preview_due_date',
        store=True,
    )

    @api.depends('age_days')
    def _compute_preview_due_date(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.preview_due_date = today + timedelta(days=rec.age_days)

    @api.model
    def _refresh_preview_due_dates(self):
        today = fields.Date.context_today(self)
        for rec in self.search([]):
            rec.preview_due_date = today + timedelta(days=rec.age_days)

    @api.depends('vaccine_id.name', 'age_label', 'age_days', 'applicable_chicken_type')
    def _compute_name(self):
        for rec in self:
            label = rec.age_label or f"{rec.age_days} days"
            type_labels = dict(self._fields['applicable_chicken_type'].selection)
            type_label = type_labels.get(rec.applicable_chicken_type, 'All Types')
            rec.name = f"{rec.vaccine_id.name or ''} @ {label} - {type_label}"

    def action_open_calendar(self):
        self.ensure_one()
        action = self.env.ref('farm_chicken_management.action_vaccine_schedule').read()[0]
        action['view_mode'] = 'calendar'
        action['views'] = [(self.env.ref('farm_chicken_management.view_vaccine_schedule_calendar').id, 'calendar')]
        action['res_id'] = False
        return action

    @api.constrains('age_days')
    def _check_age(self):
        for rec in self:
            if rec.age_days < 0:
                raise ValidationError('Due age cannot be negative.')


class VaccineBatchSchedule(models.Model):
    _name = 'vaccine.batch.schedule'
    _description = 'Batch Vaccination Schedule / Record'
    _order = 'due_date'

    batch_id = fields.Many2one('chicken.batch', string='Batch', required=True, ondelete='cascade')
    vaccine_id = fields.Many2one('vaccine.vaccine', string='Vaccine', required=True)
    schedule_template_id = fields.Many2one('vaccine.schedule', string='Schedule Template')
    due_date = fields.Date(string='Due Date', required=True)
    done_date = fields.Date(string='Given Date')
    quantity_used = fields.Float(string='Quantity Used', default=0.0)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('overdue', 'Overdue'),
        ('done', 'Done'),
    ], string='Status', default='pending', required=True)
    note = fields.Text(string='Note')
    email_sent = fields.Boolean(default=False)

    @api.depends('vaccine_id.name', 'batch_id.name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.vaccine_id.name or ''} - {rec.batch_id.name or ''}"

    def write(self, vals):
        mark_done_ctx = self.env.context.get('vaccine_mark_done')
        if not mark_done_ctx:
            if vals.get('state') == 'done' and any(rec.state != 'done' for rec in self):
                raise ValidationError('Use the "Mark Done" button to complete a vaccination (stock is checked there).')
            if 'quantity_used' in vals and any(rec.state == 'done' for rec in self):
                raise ValidationError('This vaccination is already marked done; Quantity Used cannot be changed.')
        return super().write(vals)

    def action_mark_done(self):
        for rec in self:
            if rec.quantity_used <= 0:
                raise ValidationError('Enter Quantity Used before marking vaccination done.')
            rec.vaccine_id.invalidate_recordset(['current_stock', 'total_used'])
            if rec.vaccine_id.current_stock < rec.quantity_used:
                raise ValidationError(
                    f'Insufficient stock for {rec.vaccine_id.name}. Current stock: {rec.vaccine_id.current_stock}.'
                )
            rec.with_context(vaccine_mark_done=True).write({
                'state': 'done',
                'done_date': rec.done_date or fields.Date.context_today(rec),
            })

    def _cron_check_due_and_remind(self):
        self.env['vaccine.schedule'].sudo()._refresh_preview_due_dates()
        today = fields.Date.context_today(self)
        pending = self.search([('state', '=', 'pending'), ('due_date', '<=', today)])
        for rec in pending:
            if rec.due_date < today:
                rec.state = 'overdue'
            batch = rec.batch_id
            summary = f"Vaccine Due: {rec.vaccine_id.name}"
            existing = self.env['mail.activity'].search([
                ('res_model', '=', 'chicken.batch'),
                ('res_id', '=', batch.id),
                ('summary', '=', summary),
                ('date_deadline', '=', rec.due_date),
            ], limit=1)
            if not existing:
                batch.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=rec.due_date,
                    summary=summary,
                    note=f"Batch {batch.name}: vaccine '{rec.vaccine_id.name}' is due on {rec.due_date}.",
                )

            recipient = (batch.notify_email or '').strip()
            if not rec.email_sent and recipient:
                mail = self.env['mail.mail'].sudo().create({
                    'email_to': recipient,
                    'subject': summary,
                    'body_html': (
                        f"<p>Batch <strong>{batch.name}</strong>: "
                        f"vaccine <strong>{rec.vaccine_id.name}</strong> "
                        f"is due on {rec.due_date}.</p>"
                    ),
                    'model': 'vaccine.batch.schedule',
                    'res_id': rec.id,
                })
                mail.send()
                rec.email_sent = True
