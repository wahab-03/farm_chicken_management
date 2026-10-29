from odoo import fields, models


class FarmExpense(models.Model):
    _name = 'farm.expense'
    _description = 'Farm Expense'
    _order = 'date desc'

    date = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    category = fields.Selection([
        ('utilities', 'Utilities'),
        ('employee', 'Employee Expense'),
        ('feed', 'Feed Expense'),
        ('vaccine', 'Vaccine Expense'),
        ('chicken_purchase', 'Chicken Purchase Expense'),
        ('incubator', 'Incubator-related Expense'),
        ('conveyance', 'Conveyance Bill'),
        ('other', 'Other Farm Expenses'),
    ], string='Category', required=True)
    amount = fields.Float(string='Amount', required=True)
    description = fields.Text(string='Description')
