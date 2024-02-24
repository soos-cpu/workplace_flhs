# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

{
    "name": "delivery_jd",
    "author": "soos",
    "version": "16.0.0.0.1",
    "category": "Project",
    "website": "https://www.sooscake.site",
    "depends": ["delivery", "delivery_jd_hooks"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
        "views/delivery_view.xml",
    ],
    "installable": True,
    'application': True,
    'license': 'LGPL-3',
}
