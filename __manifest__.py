{
    'name': 'Farm Chicken Management',
    'version': '18.0.2.0.6',
    'category': 'Industries',
    'summary': 'Poultry / Chicken Farm Management (Batch, Vaccine, Feed, Egg, Mortality, Sale, Incubator, Expense)',
    'description': """
Chicken / Poultry Farm Management
==================================
Full custom module covering:
- Chicken Purchase Entry, Category & Inventory (Batch management)
- Batch Information Dashboard
- Vaccine Management with age-wise schedule & reminders
- Feed / Food Management (Ready-made + Self-Mixed recipes, age-wise mapping)
- Daily Egg Production
- Chicken Mortality tracking
- Chicken Sale (Live / Ready-to-Cook, Live / Future Sale)
- Incubator / Hatching Management
- Hatching Schedule with auto expected-date calculation
- Failed / Damaged Eggs tracking
- Baby Chicken Management
- Expense Management
- Baby Chick Sales
- Planned-sale reservation and Ready-to-Cook processed-weight tracking
- Poultry Farming Dashboard (KPIs, charts, filters)
""",
    'author': 'Custom Development',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'views/chicken_batch_views.xml',
        'views/vaccine_views.xml',
        'views/feed_views.xml',
        'views/egg_production_views.xml',
        'views/mortality_views.xml',
        'views/sale_views.xml',
        'views/incubator_views.xml',
        'views/baby_chicken_views.xml',
        'views/expense_views.xml',
        'views/menu_views.xml',
        'views/dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'farm_chicken_management/static/src/scss/chicken_farm_dashboard.scss',
            'farm_chicken_management/static/src/js/chicken_farm_dashboard.js',
            'farm_chicken_management/static/src/xml/chicken_farm_dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
