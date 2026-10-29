from odoo import api, fields, models
from odoo.exceptions import ValidationError


class BabyChickenStock(models.Model):
    _name = 'baby.chicken.stock'
    _description = 'Baby Chicken Stock'
    _order = 'hatching_date desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    hatching_batch_id = fields.Many2one('incubator.hatching.batch', string='Hatching Batch', ondelete='set null')
    category = fields.Char(string='Category')
    quantity = fields.Integer(string='Produced Quantity', required=True)
    sold_quantity = fields.Integer(string='Sold Quantity', compute='_compute_stock')
    current_quantity = fields.Integer(string='Current Quantity', compute='_compute_stock')
    hatching_date = fields.Date(string='Hatching Date')
    age_days = fields.Integer(string='Age (Days)', compute='_compute_age')
    sale_ids = fields.One2many('baby.chicken.sale', 'baby_stock_id', string='Sales')
    converted_batch_id = fields.Many2one('chicken.batch', string='Converted to Batch', readonly=True, copy=False)
    state = fields.Selection([
        ('in_stock', 'In Stock'),
        ('converted', 'Converted to Regular Batch'),
    ], string='Status', default='in_stock')

    @api.depends('hatching_date')
    def _compute_age(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.age_days = (today - rec.hatching_date).days if rec.hatching_date else 0

    @api.depends('quantity', 'sale_ids.quantity', 'sale_ids.state')
    def _compute_stock(self):
        for rec in self:
            sold = sum(rec.sale_ids.filtered(lambda s: s.state == 'sold').mapped('quantity'))
            rec.sold_quantity = sold
            rec.current_quantity = rec.quantity - sold

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('baby.chicken.stock') or 'New'
        rec = super().create(vals)
        if rec.quantity <= 0:
            raise ValidationError('Baby chick quantity must be greater than zero.')
        return rec

    def action_convert_to_batch(self):
        for rec in self:
            if rec.state == 'converted':
                continue
            if rec.current_quantity <= 0:
                raise ValidationError('Cannot convert baby chick stock with no current quantity.')
            batch = self.env['chicken.batch'].create({
                'purchase_date': rec.hatching_date or fields.Date.context_today(rec),
                'chicken_type': 'farmer_poultry',
                'chicken_category': 'baby_chicks',
                'initial_quantity': rec.current_quantity,
                'age_months_at_purchase': 0.0,
                'purchase_price': 0.0,
                'note': f"Converted from Baby Chicken Stock {rec.name} (Hatching Batch: {rec.hatching_batch_id.name or ''})",
                'baby_chicken_source_id': rec.id,
            })
            rec.write({'state': 'converted', 'converted_batch_id': batch.id})
        return True
