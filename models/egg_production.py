from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EggProduction(models.Model):
    _name = 'egg.production'
    _description = 'Daily Egg Production'
    _order = 'date desc'

    date = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    batch_id = fields.Many2one('chicken.batch', string='Batch', required=True, ondelete='cascade')
    chicken_type = fields.Selection(related='batch_id.chicken_type', string='Chicken Type', store=True, readonly=True)
    quantity = fields.Integer(string='Number of Eggs', required=True)
    note = fields.Char(string='Note')

    @api.constrains('quantity')
    def _check_quantity(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError('Egg quantity must be greater than zero.')
