{
    'name': 'AS400 Integration',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Integration',
    'summary': 'REST API bridge between Odoo and the AS400 facility/material requisition system',
    'description': """
AS400 Integration
==================
Exposes and consumes a small set of REST endpoints connecting Odoo to AS400:

1. Inbound  - AS400 pushes a stock quantity update for a material           (AS400 -> Odoo)
2. Inbound  - AS400 pulls daily consumption (WH/Stock -> Production moves)  (AS400 -> Odoo)
3. Outbound - Odoo pushes a paid customer invoice to AS400 on demand        (Odoo -> AS400)
4. Inbound  - AS400 pushes new assets into the Asset Management app         (AS400 -> Odoo)

All inbound calls are authenticated with a per-company API key and are strictly
scoped to the company that owns the matching key - no cross-company data ever
leaves or enters through another company's key. Every call (inbound or
outbound) is logged for audit and troubleshooting.
""",
    'author': 'Baramej',
    'website': 'https://baramej.om',
    'license': 'LGPL-3',
    'depends': ['base', 'stock', 'account', 'asset_management'],
    'data': [
        'security/as400_security.xml',
        'security/ir.model.access.csv',
        'views/as400_config_views.xml',
        'views/as400_api_log_views.xml',
        'views/account_move_views.xml',
        'views/product_views.xml',
        'views/account_asset_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
