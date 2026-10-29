from odoo import api, fields, models
from odoo.exceptions import ValidationError


class IncubatorDevice(models.Model):
    _name = 'incubator.device'
    _description = 'Incubator Machine'

    name = fields.Char(string='Incubator ID / Name', required=True)
    capacity = fields.Integer(string='Egg Capacity')
    location = fields.Char(string='Location')
    note = fields.Text(string='Note')


class IncubatorHatchingBatch(models.Model):
    _name = 'incubator.hatching.batch'
    _description = 'Hatching Batch'
    _order = 'start_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Hatching Batch Number', default='New', copy=False, readonly=True)
    start_date = fields.Date(string='Start Date', default=fields.Date.context_today, required=True)
    egg_category = fields.Selection([
        ('deshi', 'Deshi'),
        ('farmer_poultry', 'Farmer / Poultry'),
        ('pahari', 'Pahari'),
    ], string='Chicken Category')
    number_of_eggs = fields.Integer(string='Number of Eggs', required=True)
    incubator_id = fields.Many2one('incubator.device', string='Incubator')
    hatching_duration = fields.Selection([('13', '13 Days'), ('21', '21 Days')],
                                         string='Hatching Duration', default='21', required=True)
    expected_hatching_date = fields.Date(string='Expected Hatching Date', compute='_compute_expected_date', store=True)
    actual_hatching_date = fields.Date(string='Actual Hatching Date')
    hatched_chicks = fields.Integer(string='Hatched Chicks')
    failed_egg_ids = fields.One2many('incubator.failed.egg', 'hatching_batch_id', string='Failed / Damaged Eggs')
    total_failed_damaged = fields.Integer(string='Total Failed/Damaged', compute='_compute_failed_totals', store=True)
    baby_chicks_produced = fields.Integer(string='Baby Chicks Produced', compute='_compute_failed_totals', store=True)
    baby_chick_stock_id = fields.Many2one('baby.chicken.stock', string='Baby Chick Stock', readonly=True)
    status = fields.Selection([
        ('incubating', 'Incubating'),
        ('hatched', 'Hatched'),
        ('hatching_not_completed', 'Hatching Not Completed'),
    ], string='Status', default='incubating', compute='_compute_status', store=True)

    @api.depends('start_date', 'hatching_duration')
    def _compute_expected_date(self):
        for rec in self:
            rec.expected_hatching_date = (
                fields.Date.add(rec.start_date, days=int(rec.hatching_duration))
                if rec.start_date and rec.hatching_duration else False
            )

    @api.depends('number_of_eggs', 'failed_egg_ids.failed_eggs', 'failed_egg_ids.damaged_eggs', 'hatched_chicks')
    def _compute_failed_totals(self):
        for rec in self:
            failed = sum(rec.failed_egg_ids.mapped('failed_eggs'))
            damaged = sum(rec.failed_egg_ids.mapped('damaged_eggs'))
            rec.total_failed_damaged = failed + damaged
            rec.baby_chicks_produced = rec.hatched_chicks if rec.hatched_chicks else max(
                rec.number_of_eggs - rec.total_failed_damaged, 0
            )

    @api.depends('actual_hatching_date', 'expected_hatching_date')
    def _compute_status(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.actual_hatching_date:
                rec.status = 'hatched'
            elif rec.expected_hatching_date and rec.expected_hatching_date < today:
                rec.status = 'hatching_not_completed'
            else:
                rec.status = 'incubating'

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('incubator.hatching.batch') or 'New'
        rec = super().create(vals)
        rec._validate_totals()
        return rec

    def write(self, vals):
        res = super().write(vals)
        if {'number_of_eggs', 'hatched_chicks'} & set(vals):
            self._validate_totals()
        return res

    def _validate_totals(self):
        for rec in self:
            if rec.number_of_eggs <= 0:
                raise ValidationError('Number of Eggs must be greater than zero.')
            if rec.hatched_chicks < 0:
                raise ValidationError('Hatched Chicks cannot be negative.')
            if rec.total_failed_damaged > rec.number_of_eggs:
                raise ValidationError('Failed + Damaged eggs cannot exceed total eggs.')
            if rec.hatched_chicks + rec.total_failed_damaged > rec.number_of_eggs:
                raise ValidationError('Hatched + Failed + Damaged eggs cannot exceed total eggs.')

    def action_mark_hatched(self):
        for rec in self:
            rec._validate_totals()
            if rec.baby_chick_stock_id:
                continue
            actual_date = rec.actual_hatching_date or fields.Date.context_today(rec)
            chicks = rec.hatched_chicks or max(rec.number_of_eggs - rec.total_failed_damaged, 0)
            if chicks <= 0:
                raise ValidationError('Hatching must produce at least one baby chick.')
            rec.write({'actual_hatching_date': actual_date, 'hatched_chicks': chicks})
            if not rec.baby_chick_stock_id:
                stock = self.env['baby.chicken.stock'].create({
                    'hatching_batch_id': rec.id,
                    'category': dict(rec._fields['egg_category'].selection).get(rec.egg_category) or False,
                    'quantity': chicks,
                    'hatching_date': actual_date,
                })
                rec.baby_chick_stock_id = stock.id

    def _cron_check_hatching_overdue(self):
        today = fields.Date.context_today(self)
        not_hatched = self.search([('actual_hatching_date', '=', False)])
        not_hatched.modified(['expected_hatching_date'])
        overdue = self.search([
            ('actual_hatching_date', '=', False),
            ('expected_hatching_date', '<', today),
        ])
        for rec in overdue:
            summary = 'Hatching Not Completed'
            existing = self.env['mail.activity'].search([
                ('res_model', '=', 'incubator.hatching.batch'),
                ('res_id', '=', rec.id),
                ('summary', '=', summary),
            ], limit=1)
            if not existing:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=today,
                    summary=summary,
                    note=f'Hatching batch {rec.name} passed expected date ({rec.expected_hatching_date}).',
                )

    def _cron_check_hatching_due_reminder(self):
        today = fields.Date.context_today(self)
        due_today = self.search([
            ('actual_hatching_date', '=', False),
            ('expected_hatching_date', '=', today),
        ])
        for rec in due_today:
            summary = 'Hatching Expected Today'
            existing = self.env['mail.activity'].search([
                ('res_model', '=', 'incubator.hatching.batch'),
                ('res_id', '=', rec.id),
                ('summary', '=', summary),
                ('date_deadline', '=', today),
            ], limit=1)
            if not existing:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=today,
                    summary=summary,
                    note=f'Hatching batch {rec.name} is expected to hatch today.',
                )


class IncubatorFailedEgg(models.Model):
    _name = 'incubator.failed.egg'
    _description = 'Failed / Damaged Eggs'
    _order = 'date desc'

    date = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    hatching_batch_id = fields.Many2one('incubator.hatching.batch', string='Hatching Batch', required=True, ondelete='cascade')
    egg_category = fields.Char(string='Egg Category')
    total_eggs = fields.Integer(string='Total Eggs (Checked)')
    failed_eggs = fields.Integer(string='Failed Eggs')
    damaged_eggs = fields.Integer(string='Damaged Eggs')
    reason = fields.Text(string='Reason')

    @api.constrains('total_eggs', 'failed_eggs', 'damaged_eggs', 'hatching_batch_id')
    def _check_values(self):
        for rec in self:
            if min(rec.total_eggs, rec.failed_eggs, rec.damaged_eggs) < 0:
                raise ValidationError('Egg quantities cannot be negative.')
            if rec.failed_eggs + rec.damaged_eggs > rec.total_eggs:
                raise ValidationError('Failed + Damaged eggs cannot exceed checked eggs.')
            if rec.hatching_batch_id and rec.hatching_batch_id.total_failed_damaged > rec.hatching_batch_id.number_of_eggs:
                raise ValidationError('Total failed/damaged eggs cannot exceed the hatching batch quantity.')
