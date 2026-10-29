from odoo import api, fields, models
from odoo.exceptions import ValidationError


FEED_STAGE_SELECTION = [
    ('baby', 'Baby Feed (0-1 Month)'),
    ('grower', 'Grower Feed (1-2 Month)'),
    ('grower_layer', 'Grower/Layer Feed (2-4 Month)'),
    ('adult_layer', 'Adult/Layer Feed (4+ Month)'),
]


class FeedIngredient(models.Model):
    _name = 'feed.ingredient'
    _description = 'Feed Ingredient Master'
    _order = 'name'

    name = fields.Char(string='Ingredient Name', required=True)
    uom = fields.Char(string='Unit of Measure', default='kg', required=True)
    purchase_ids = fields.One2many('feed.ingredient.purchase', 'ingredient_id', string='Purchase History')
    used_in_recipe_line_ids = fields.One2many('feed.recipe.line', 'ingredient_id', string='Used In Recipes')
    current_stock = fields.Float(string='Current Stock', compute='_compute_stock')

    def _compute_stock(self):
        MixingLine = self.env['feed.mixing.line']
        for ing in self:
            purchased = sum(ing.purchase_ids.mapped('quantity'))
            consumed = sum(MixingLine.search([
                ('ingredient_id', '=', ing.id),
                ('mixing_id.state', '=', 'done'),
            ]).mapped('quantity_used'))
            ing.current_stock = purchased - consumed


class FeedIngredientPurchase(models.Model):
    _name = 'feed.ingredient.purchase'
    _description = 'Raw Ingredient Purchase'
    _order = 'purchase_date desc'

    ingredient_id = fields.Many2one('feed.ingredient', string='Ingredient', required=True, ondelete='cascade')
    purchase_date = fields.Date(string='Purchase Date', default=fields.Date.context_today, required=True)
    quantity = fields.Float(string='Quantity', required=True)
    price = fields.Float(string='Purchase Price')
    supplier_id = fields.Many2one('res.partner', string='Supplier')
    purchase_location = fields.Char(string='Purchase Location')

    @api.constrains('quantity', 'price')
    def _check_values(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError('Ingredient purchase quantity must be greater than zero.')
            if rec.price < 0:
                raise ValidationError('Purchase price cannot be negative.')


class FeedProduct(models.Model):
    _name = 'feed.product'
    _description = 'Feed Product (Purchased or Self-Mixed)'
    _order = 'name'

    name = fields.Char(string='Feed Name', required=True)
    feed_category = fields.Selection(FEED_STAGE_SELECTION, string='Feed Category (Age Stage)', required=True)
    source_type = fields.Selection([
        ('purchased', 'Ready-made / Purchased'),
        ('self_mixed', 'Self-Mixed'),
    ], string='Source', default='purchased', required=True)
    purchase_ids = fields.One2many('feed.product.purchase', 'feed_id', string='Purchase History')
    mixing_ids = fields.One2many('feed.mixing', 'output_feed_id', string='Mixing History')
    consumption_ids = fields.One2many('feed.consumption', 'feed_id', string='Consumption History')
    current_stock = fields.Float(
        string='Current Stock (kg)',
        compute='_compute_stock',
        store=True,
    )

    @api.depends(
        'purchase_ids',
        'purchase_ids.quantity',
        'mixing_ids',
        'mixing_ids.state',
        'mixing_ids.quantity_produced',
        'consumption_ids',
        'consumption_ids.quantity',
    )
    def _compute_stock(self):
        for feed in self:
            purchased = sum(feed.purchase_ids.mapped('quantity'))
            mixed = sum(feed.mixing_ids.filtered(lambda m: m.state == 'done').mapped('quantity_produced'))
            consumed = sum(feed.consumption_ids.mapped('quantity'))
            feed.current_stock = purchased + mixed - consumed

    def _link_unassigned_mixings(self):
        Mixing = self.env['feed.mixing']
        for feed in self.filtered(lambda r: r.source_type == 'self_mixed' and r.name and r.feed_category):
            unassigned = Mixing.search([
                ('output_feed_id', '=', False),
                ('state', '=', 'done'),
                ('recipe_id.name', '=', feed.name),
                ('recipe_id.target_feed_category', '=', feed.feed_category),
            ])
            if unassigned:
                unassigned.write({'output_feed_id': feed.id})

    def _postprocess_self_mixed_link(self):
        self.filtered(lambda r: r.source_type == 'self_mixed')._link_unassigned_mixings()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._postprocess_self_mixed_link()
        return records

    def write(self, vals):
        result = super().write(vals)
        if {'name', 'feed_category', 'source_type'} & set(vals):
            self._postprocess_self_mixed_link()
        return result


class FeedProductPurchase(models.Model):
    _name = 'feed.product.purchase'
    _description = 'Ready-made Feed Purchase'
    _order = 'purchase_date desc'

    feed_id = fields.Many2one('feed.product', string='Feed', required=True, ondelete='cascade',
                               domain=[('source_type', '=', 'purchased')])
    purchase_date = fields.Date(string='Purchase Date', default=fields.Date.context_today, required=True)
    purchase_location = fields.Char(string='Purchase Location')
    quantity = fields.Float(string='Quantity (kg)', required=True)
    price = fields.Float(string='Purchase Price')
    supplier_id = fields.Many2one('res.partner', string='Supplier')

    @api.constrains('quantity', 'price')
    def _check_values(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError('Feed purchase quantity must be greater than zero.')
            if rec.price < 0:
                raise ValidationError('Purchase price cannot be negative.')


class FeedRecipe(models.Model):
    _name = 'feed.recipe'
    _description = 'Feed Formula / Recipe'

    name = fields.Char(string='Formula Name', required=True)
    target_feed_category = fields.Selection(FEED_STAGE_SELECTION, string='Target Feed Category', required=True)
    line_ids = fields.One2many('feed.recipe.line', 'recipe_id', string='Ingredients')
    total_quantity = fields.Float(string='Formula Total (kg)', compute='_compute_total', store=True)
    note = fields.Text(string='Note')

    @api.depends('line_ids.quantity')
    def _compute_total(self):
        for rec in self:
            rec.total_quantity = sum(rec.line_ids.mapped('quantity'))

    def action_mix_now(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Prepare Feed',
            'res_model': 'feed.mixing',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_recipe_id': self.id},
        }


class FeedRecipeLine(models.Model):
    _name = 'feed.recipe.line'
    _description = 'Feed Formula Ingredient Line'

    recipe_id = fields.Many2one('feed.recipe', string='Formula', required=True, ondelete='cascade')
    ingredient_id = fields.Many2one('feed.ingredient', string='Ingredient', required=True)
    quantity = fields.Float(string='Quantity (kg)', required=True)

    @api.constrains('quantity')
    def _check_quantity(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError('Formula ingredient quantity must be greater than zero.')


class FeedMixing(models.Model):
    _name = 'feed.mixing'
    _description = 'Feed Mixing / Preparation'
    _order = 'mixing_date desc'

    name = fields.Char(string='Batch / Lot Number', default='New', copy=False, readonly=True)
    recipe_id = fields.Many2one('feed.recipe', string='Feed Formula', required=True)
    mixing_date = fields.Date(string='Prepared Date', default=fields.Date.context_today, required=True)
    output_feed_id = fields.Many2one('feed.product', string='Prepared Feed', domain=[('source_type', '=', 'self_mixed')])
    quantity_produced = fields.Float(string='Prepared Quantity (kg)', compute='_compute_quantity_produced', store=True)
    line_ids = fields.One2many('feed.mixing.line', 'mixing_id', string='Raw Ingredients Used')
    state = fields.Selection([('draft', 'Draft'), ('done', 'Prepared')], default='draft', string='Status', required=True)

    @api.depends('recipe_id.line_ids.quantity', 'line_ids.quantity_used')
    def _compute_quantity_produced(self):
        for rec in self:
            if rec.line_ids:
                rec.quantity_produced = sum(rec.line_ids.mapped('quantity_used'))
            else:
                rec.quantity_produced = sum(rec.recipe_id.line_ids.mapped('quantity'))

    @api.onchange('recipe_id')
    def _onchange_recipe(self):
        for rec in self:
            if rec.recipe_id:
                rec.line_ids = [(5, 0, 0)] + [
                    (0, 0, {
                        'ingredient_id': line.ingredient_id.id,
                        'quantity_used': line.quantity,
                    }) for line in rec.recipe_id.line_ids
                ]

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('feed.mixing') or 'New'
        return super().create(vals)

    def action_confirm_mixing(self):
        for rec in self:
            if rec.state == 'done':
                continue
            if rec.quantity_produced <= 0:
                raise ValidationError('Prepared quantity must be greater than zero.')
            if not rec.line_ids:
                rec._onchange_recipe()
            required = {}
            for line in rec.line_ids:
                if line.quantity_used <= 0:
                    raise ValidationError(f'Ingredient {line.ingredient_id.name} has invalid quantity.')
                required[line.ingredient_id] = required.get(line.ingredient_id, 0.0) + line.quantity_used
            self.env['feed.ingredient'].invalidate_model(['current_stock'])
            for ingredient, needed in required.items():
                if ingredient.current_stock < needed:
                    raise ValidationError(
                        f'Insufficient stock of {ingredient.name}. '
                        f'Available: {ingredient.current_stock} kg.'
                    )
            if not rec.output_feed_id:
                feed = self.env['feed.product'].search([
                    ('source_type', '=', 'self_mixed'),
                    ('feed_category', '=', rec.recipe_id.target_feed_category),
                    ('name', '=', rec.recipe_id.name),
                ], limit=1)
                if not feed:
                    feed = self.env['feed.product'].create({
                        'name': rec.recipe_id.name,
                        'feed_category': rec.recipe_id.target_feed_category,
                        'source_type': 'self_mixed',
                    })
                rec.output_feed_id = feed
            rec.output_feed_id._link_unassigned_mixings()
            rec.state = 'done'


class FeedMixingLine(models.Model):
    _name = 'feed.mixing.line'
    _description = 'Feed Mixing Ingredient Consumption Line'

    mixing_id = fields.Many2one('feed.mixing', string='Mixing', required=True, ondelete='cascade')
    ingredient_id = fields.Many2one('feed.ingredient', string='Ingredient', required=True)
    quantity_used = fields.Float(string='Quantity Used (kg)', required=True)


class FeedConsumption(models.Model):
    _name = 'feed.consumption'
    _description = 'Batch-wise Feed Consumption'
    _order = 'date desc'

    date = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    batch_id = fields.Many2one('chicken.batch', string='Batch', required=True, ondelete='cascade')
    feed_id = fields.Many2one('feed.product', string='Feed', required=True)
    quantity = fields.Float(string='Quantity Used (kg)', required=True)
    note = fields.Char(string='Note')

    @api.constrains('quantity', 'feed_id')
    def _check_stock(self):
        for rec in self:
            if rec.quantity <= 0:
                raise ValidationError('Feed consumption must be greater than zero.')

            available = rec.feed_id.current_stock
            if rec.id:
                available += rec.quantity

            if rec.quantity > available:
                raise ValidationError('Feed consumption exceeds available stock.')
