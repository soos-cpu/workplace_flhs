# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    module_delivery_jd_mix_rule = fields.Boolean("基於規則的京東物流連接器")

    jd_mix_rule_app_key = fields.Char(string="appKey", config_parameter="delivery_jd_mix_rule.jd_mix_rule_app_key",
                                      help="應用的appKey，可從【控制台-應用管理-概覽】中查看")
    jd_mix_rule_app_secret = fields.Char(string="appSecret",
                                         config_parameter="delivery_jd_mix_rule.jd_mix_rule_app_secret",
                                         help="應用的appSecret，可從【控制台-應用管理-概覽】中查看")
    jd_mix_rule_access_token = fields.Char(string="accessToken",
                                           config_parameter="delivery_jd_mix_rule.jd_mix_rule_access_token",
                                           help="客戶驗證的通過後獲取的密鑰，有效期一年")
    jd_mix_rule_customer_code = fields.Char(string="客戶編碼",
                                            config_parameter="delivery_jd_mix_rule.jd_mix_rule_customer_code",
                                            help="客戶編碼")
