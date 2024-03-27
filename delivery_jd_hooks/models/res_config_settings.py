# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    module_delivery_jd = fields.Boolean("京东物流连接器")
    jd_app_key = fields.Char(string="appKey", config_parameter="delivery_jd.jd_app_key",
                             help="应用的appKey，可从【控制台-应用管理-概览】中查看")
    jd_app_secret = fields.Char(string="appSecret", config_parameter="delivery_jd.jd_app_secret",
                                help="应用的appSecret，可从【控制台-应用管理-概览】中查看")

    @api.model
    def get_jd_access_info(self):
        icp_get = self.env['ir.config_parameter'].sudo().get_param
        result = icp_get('delivery_jd.jd_app_key'), icp_get('delivery_jd.jd_app_secret')
        return result
