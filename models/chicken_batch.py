from datetime import date
from odoo import api, fields, models


class ChickenBatch(models.Model):
    _name = 'chicken.batch'
    _description = 'Chicken Batch (Purchase Entry + Batch Info)'
    _order = 'purchase_date desc, id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Batch Number', readonly=True, copy=False, default='/', tracking=True)

    purchase_date = fields.Date(string='Purchase Date', default=fields.Date.context_today, required=True, tracking=True)
    chicken_type = fields.Selection([
        ('deshi', 'Deshi'),
        ('farmer_poultry', 'Farmer / Poultry'),
        ('pahari', 'Pahari'),
    ], string='Chicken Type', required=True, tracking=True)
    chicken_category = fields.Selection([
        ('morog', 'Morog (Rooster)'),
        ('murgi', 'Murgi (Hen)'),
        ('baby_chicks', 'Baby Chicks'),
    ], string='Chicken Category', required=True, tracking=True)
    initial_quantity = fields.Integer(string='Total Quantity (Purchased)', required=True, default=0, tracking=True)
    current_age_days = fields.Integer(string='Current Age (Days)', default=0)
    age_months_at_purchase = fields.Float(string='Age at Purchase (Months)',
                                          compute='_compute_age_months_at_purchase', store=True)
    purchase_price = fields.Float(string='Purchase Price (Total)')
    supplier_id = fields.Many2one('res.partner', string='Supplier')
    notify_email = fields.Char(string='Vaccine Notification Email')
    note = fields.Text(string='Note')

    baby_chicken_source_id = fields.Many2one('baby.chicken.stock', string='Source Baby Chick Stock', copy=False)

    mortality_ids = fields.One2many('chicken.mortality', 'batch_id', string='Mortality Records')
    sale_ids = fields.One2many('chicken.sale', 'batch_id', string='Sales')
    egg_ids = fields.One2many('egg.production', 'batch_id', string='Egg Production')
    vaccine_schedule_ids = fields.One2many('vaccine.batch.schedule', 'batch_id', string='Vaccination Schedule')
    feed_consumption_ids = fields.One2many('feed.consumption', 'batch_id', string='Feed Consumption')

    total_mortality = fields.Integer(string='Total Mortality', compute='_compute_totals', store=True)
    total_sold = fields.Integer(string='Total Sold', compute='_compute_totals', store=True)
    total_eggs = fields.Integer(string='Total Eggs Produced', compute='_compute_totals', store=True)
    total_feed_consumed = fields.Float(string='Total Feed Consumed (kg)', compute='_compute_totals', store=True)
    current_quantity = fields.Integer(string='Current Quantity', compute='_compute_totals', store=True, tracking=True)
    reserved_quantity = fields.Integer(string='Reserved for Planned Sales', compute='_compute_totals', store=True)
    available_quantity = fields.Integer(string='Available After Reservations', compute='_compute_totals', store=True)

    current_age_months = fields.Float(string='Current Age (Months)', compute='_compute_current_age')
    recommended_feed_stage = fields.Selection([
        ('baby', 'Baby Feed (0-1 Month)'),
        ('grower', 'Grower Feed (1-2 Month)'),
        ('grower_layer', 'Grower/Layer Feed (2-4 Month)'),
        ('adult_layer', 'Adult/Layer Feed (4+ Month)'),
    ], string='Recommended Feed Stage', compute='_compute_current_age')

    active = fields.Boolean(default=True)

    @api.constrains('initial_quantity', 'current_age_days', 'age_months_at_purchase', 'purchase_price')
    def _check_purchase_values(self):
        from odoo.exceptions import ValidationError
        for batch in self:
            if batch.initial_quantity <= 0:
                raise ValidationError('Purchase quantity must be greater than zero.')
            if batch.current_age_days < 0 or batch.age_months_at_purchase < 0:
                raise ValidationError('Age at purchase cannot be negative.')
            if batch.purchase_price < 0:
                raise ValidationError('Purchase price cannot be negative.')

    @api.model
    def create(self, vals):
        if not vals.get('name') or vals.get('name') == '/':
            vals['name'] = self.env['ir.sequence'].next_by_code('chicken.batch') or '/'
        batch = super().create(vals)
        batch._generate_vaccine_schedule()
        return batch

    @api.depends('initial_quantity', 'mortality_ids.total_dead',
                 'sale_ids.quantity', 'sale_ids.state',
                 'egg_ids.quantity', 'feed_consumption_ids.quantity')
    def _compute_totals(self):
        for batch in self:
            batch.total_mortality = sum(batch.mortality_ids.mapped('total_dead'))
            delivered_sales = batch.sale_ids.filtered(lambda s: s.state == 'delivered')
            batch.total_sold = sum(delivered_sales.mapped('quantity'))
            planned_sales = batch.sale_ids.filtered(lambda s: s.state == 'planned')
            batch.reserved_quantity = sum(planned_sales.mapped('quantity'))
            batch.total_eggs = sum(batch.egg_ids.mapped('quantity'))
            batch.total_feed_consumed = sum(batch.feed_consumption_ids.mapped('quantity'))
            batch.current_quantity = batch.initial_quantity - batch.total_mortality - batch.total_sold
            batch.available_quantity = batch.current_quantity - batch.reserved_quantity

    @api.depends('current_age_days')
    def _compute_age_months_at_purchase(self):
        for batch in self:
            batch.age_months_at_purchase = (batch.current_age_days or 0) / 30.0

    @api.model
    def _backfill_current_age_days(self):
        """Existing batches only have months: fill the new days input (idempotent,
        months are left untouched)."""
        self.env.cr.execute("""
            UPDATE chicken_batch
               SET current_age_days = ROUND(age_months_at_purchase * 30)::integer
             WHERE COALESCE(current_age_days, 0) = 0
               AND COALESCE(age_months_at_purchase, 0) > 0
        """)
        self.invalidate_model(['current_age_days'])

    @api.depends('purchase_date', 'age_months_at_purchase')
    def _compute_current_age(self):
        for batch in self:
            if batch.purchase_date:
                days_since_purchase = (fields.Date.context_today(batch) - batch.purchase_date).days
                age_days_at_purchase = int(round(batch.age_months_at_purchase * 30))
                total_days = age_days_at_purchase + max(days_since_purchase, 0)
            else:
                total_days = int(round(batch.age_months_at_purchase * 30))
            batch.current_age_months = round(total_days / 30.0, 2)
            months = batch.current_age_months
            if months < 1:
                batch.recommended_feed_stage = 'baby'
            elif months < 2:
                batch.recommended_feed_stage = 'grower'
            elif months < 4:
                batch.recommended_feed_stage = 'grower_layer'
            else:
                batch.recommended_feed_stage = 'adult_layer'

    def _generate_vaccine_schedule(self):
        """Auto create per-batch vaccination schedule lines from global vaccine.schedule templates,
        based on this batch's purchase_date + age offset."""
        Schedule = self.env['vaccine.schedule'].sudo().search([])
        BatchSchedule = self.env['vaccine.batch.schedule'].sudo()
        for batch in self:
            for tmpl in Schedule:
                if tmpl.applicable_chicken_type not in ('all', batch.chicken_type):
                    continue
                age_at_purchase_days = int(round(batch.age_months_at_purchase * 30))
                if tmpl.age_days < age_at_purchase_days:
                    continue
                days_until_due = tmpl.age_days - age_at_purchase_days
                due_date = fields.Date.add(batch.purchase_date, days=days_until_due)
                BatchSchedule.create({
                    'batch_id': batch.id,
                    'vaccine_id': tmpl.vaccine_id.id,
                    'schedule_template_id': tmpl.id,
                    'due_date': due_date,
                    'state': 'pending',
                })

    def action_view_mortality(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Mortality',
            'res_model': 'chicken.mortality',
            'view_mode': 'list,form',
            'domain': [('batch_id', '=', self.id)],
            'context': {'default_batch_id': self.id},
        }

    def action_view_sales(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sales',
            'res_model': 'chicken.sale',
            'view_mode': 'list,form',
            'domain': [('batch_id', '=', self.id)],
            'context': {'default_batch_id': self.id},
        }

    def action_view_eggs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Egg Production',
            'res_model': 'egg.production',
            'view_mode': 'list,form',
            'domain': [('batch_id', '=', self.id)],
            'context': {'default_batch_id': self.id},
        }
