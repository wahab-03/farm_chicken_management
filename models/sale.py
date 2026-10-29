from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ChickenSale(models.Model):
    _name = 'chicken.sale'
    _description = 'Chicken Sale'
    _order = 'sale_date desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    sale_date = fields.Date(string='Sale Date', default=fields.Date.context_today, required=True)
    batch_id = fields.Many2one('chicken.batch', string='Batch', required=True, ondelete='cascade')
    chicken_type = fields.Selection(related='batch_id.chicken_type', string='Chicken Type', store=True, readonly=True)
    chicken_category = fields.Selection(related='batch_id.chicken_category', string='Category', store=True, readonly=True)
    age_months = fields.Float(string='Chicken Age (Months)', related='batch_id.current_age_months', readonly=True)

    sale_subcategory = fields.Selection([
        ('live_bird', 'Live Chicken'),
        ('ready_to_cook', 'Ready to Cook'),
    ], string='Sale Subcategory', required=True, default='live_bird')
    sale_type = fields.Selection([
        ('live_sale', 'Live Sale'),
        ('future_sale', 'Future / Planned Sale'),
    ], string='Sale Type', required=True, default='live_sale')
    planned_delivery_date = fields.Date(string='Planned Delivery Date')
    quantity = fields.Integer(string='Total Quantity', required=True)
    processed_weight = fields.Float(string='Processed Weight (kg)')
    selling_price = fields.Float(string='Selling Price (Total)')
    customer_id = fields.Many2one('res.partner', string='Customer')
    state = fields.Selection([
        ('planned', 'Planned / Booked'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='delivered', required=True)

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('chicken.sale') or 'New'
        if vals.get('sale_type') == 'future_sale':
            vals['state'] = 'planned'
        elif vals.get('sale_type') == 'live_sale':
            vals['state'] = 'delivered'
        sale = super().create(vals)
        sale._validate_sale()
        return sale

    def write(self, vals):
        res = super().write(vals)
        self._validate_sale()
        return res

    def _validate_sale(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError('Sale quantity must be greater than zero.')
            if rec.sale_subcategory == 'ready_to_cook' and rec.processed_weight <= 0:
                raise ValidationError('Processed Weight is required and must be greater than zero for Ready-to-Cook sales.')
            if rec.sale_subcategory == 'live_bird' and rec.processed_weight:
                raise ValidationError('Processed Weight must be empty for Live Chicken sales.')
            if rec.sale_type == 'future_sale' and not rec.planned_delivery_date:
                raise ValidationError('Planned Delivery Date is required for Future / Planned Sale.')
            if rec.state == 'delivered':
                other = self.search([
                    ('id', '!=', rec.id),
                    ('batch_id', '=', rec.batch_id.id),
                    ('state', 'in', ['delivered', 'planned']),
                ])
                already_committed = sum(other.mapped('quantity'))
                if already_committed + rec.quantity > rec.batch_id.initial_quantity - rec.batch_id.total_mortality:
                    raise ValidationError(
                        f'Sale quantity exceeds available chickens in {rec.batch_id.name}. '
                        f'Available after other commitments: {rec.batch_id.initial_quantity - rec.batch_id.total_mortality - already_committed}.'
                    )
            if rec.state == 'planned':
                other = self.search([
                    ('id', '!=', rec.id),
                    ('batch_id', '=', rec.batch_id.id),
                    ('state', '=', 'planned'),
                ])
                reserved = sum(other.mapped('quantity'))
                available = rec.batch_id.initial_quantity - rec.batch_id.total_mortality - rec.batch_id.total_sold
                if reserved + rec.quantity > available:
                    raise ValidationError(
                        f'Planned sale quantity exceeds available/reservable chickens in {rec.batch_id.name}. '
                        f'Available for reservation: {max(available - reserved, 0)}.'
                    )

    @api.onchange('sale_type')
    def _onchange_sale_type(self):
        for rec in self:
            rec.state = 'delivered' if rec.sale_type == 'live_sale' else 'planned'
            if rec.sale_type == 'live_sale':
                rec.planned_delivery_date = False

    @api.onchange('sale_subcategory')
    def _onchange_sale_subcategory(self):
        for rec in self:
            if rec.sale_subcategory == 'live_bird':
                rec.processed_weight = 0.0
            elif rec.sale_subcategory == 'ready_to_cook':
                rec.sale_type = 'live_sale'
                rec.state = 'delivered'
                rec.planned_delivery_date = False
                rec.customer_id = False
                rec.selling_price = 0.0

    def action_mark_delivered(self):
        for rec in self:
            rec.write({
                'state': 'delivered',
                'sale_date': fields.Date.context_today(rec),
            })

    def action_cancel(self):
        self.write({'state': 'cancelled'})


class BabyChickenSale(models.Model):
    _name = 'baby.chicken.sale'
    _description = 'Baby Chicken Sale'
    _order = 'sale_date desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    sale_date = fields.Date(string='Sale Date', default=fields.Date.context_today, required=True)
    baby_stock_id = fields.Many2one('baby.chicken.stock', string='Baby Chicken Stock', required=True)
    category = fields.Char(related='baby_stock_id.category', readonly=True)
    quantity = fields.Integer(string='Quantity', required=True)
    selling_price = fields.Float(string='Selling Price (Total)')
    customer_id = fields.Many2one('res.partner', string='Customer')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sold', 'Sold'),
        ('cancelled', 'Cancelled'),
    ], default='draft', required=True)

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('baby.chicken.sale') or 'New'
        rec = super().create(vals)
        rec._validate_qty()
        return rec

    def _validate_qty(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError('Baby chick sale quantity must be greater than zero.')
            if rec.baby_stock_id.state == 'converted':
                raise ValidationError(
                    'This baby chick stock has already been converted to a regular batch '
                    'and cannot be sold from here.'
                )
            if rec.state == 'sold':
                other = self.search([
                    ('id', '!=', rec.id), ('baby_stock_id', '=', rec.baby_stock_id.id), ('state', '=', 'sold')
                ])
                sold = sum(other.mapped('quantity'))
                if sold + rec.quantity > rec.baby_stock_id.quantity:
                    raise ValidationError('Baby chick sale exceeds available stock.')

    def write(self, vals):
        res = super().write(vals)
        if {'quantity', 'state', 'baby_stock_id'} & set(vals):
            self.filtered(lambda r: r.state != 'cancelled')._validate_qty()
        return res

    def action_confirm(self):
        for rec in self:
            rec.state = 'sold'
            rec._validate_qty()
