from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ChickenMortality(models.Model):
    _name = 'chicken.mortality'
    _description = 'Chicken Mortality / Dead Chicken Entry'
    _order = 'date desc'

    date = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    batch_id = fields.Many2one('chicken.batch', string='Batch', required=True, ondelete='cascade')
    chicken_type = fields.Selection(related='batch_id.chicken_type', string='Chicken Type', store=True, readonly=True)
    chicken_category = fields.Selection(related='batch_id.chicken_category', string='Chicken Category', store=True, readonly=True)
    total_dead = fields.Integer(string='Total Dead', required=True)
    reason = fields.Text(string='Reason')

    @api.constrains('total_dead', 'batch_id')
    def _check_quantity(self):
        for rec in self:
            if rec.total_dead <= 0:
                raise ValidationError('Dead chicken quantity must be greater than zero.')
            other = self.search([('id', '!=', rec.id), ('batch_id', '=', rec.batch_id.id)])
            previous_dead = sum(other.mapped('total_dead'))
            delivered_sales = sum(rec.batch_id.sale_ids.filtered(
                lambda s: s.state == 'delivered'
            ).mapped('quantity'))
            if previous_dead + rec.total_dead + delivered_sales > rec.batch_id.initial_quantity:
                raise ValidationError(
                    f'Mortality exceeds available chickens in {rec.batch_id.name}. '
                    f'Current available quantity before this entry: '
                    f'{max(rec.batch_id.initial_quantity - previous_dead - delivered_sales, 0)}.'
                )
