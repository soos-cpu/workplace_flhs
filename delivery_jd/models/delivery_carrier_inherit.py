# -*- coding: utf-8 -*-

from odoo import api, fields, models, registry, SUPERUSER_ID, _
from odoo.exceptions import ValidationError
from odoo.tools.misc import hmac as hmac_tool
from werkzeug import urls
from dateutil.relativedelta import relativedelta

import requests
import json


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    delivery_type = fields.Selection(selection_add=[('jd', '京东物流')], ondelete={'jd': 'set default'})
    jd_access_token = fields.Char(string="accessToken", help="用户授权完成时平台分配的access_token")
    jd_access_expire = fields.Datetime(string="accessToken过期时间")
    # 按照京东文档的说法 refresh_token 目前并无作用
    # https://cloud.jdl.com/#/open-business-document/access-guide/158/53392 => 5.1
    jd_refresh_token = fields.Char(string="refreshToken")
    jd_refresh_expire = fields.Datetime(string="refreshToken过期时间")

    @api.model
    def get_jd_access_info(self):
        result = self.env['res.config.settings'].get_jd_access_info()
        if not all(result):
            raise ValidationError(_("请在库存-配置-设置-物流对接-京东物流连接器里填写密钥"))
        return result

    def get_jd_url(self):
        return 'https://oauth.jdl.com' if self.prod_environment else 'https://uat-oauth.jdl.com'

    def action_oauth_jd_delivery(self):
        self.ensure_one()
        oauth_url = "{jd_url}/oauth/authorize".format(jd_url=self.get_jd_url())
        base_database_url = self.get_base_url()
        metadata = {
            'delivery_carrier_id': self.id,
            'signature': hmac_tool(
                self.env(su=True), 'jd_delivery_compute_oauth_signature', str(self.id)
            ),
        }
        key, secret = self.get_jd_access_info()
        oauth_url_params = {
            'response_type': 'code',
            'client_id': key,
            'redirect_uri': urls.url_join(base_database_url, 'jd_delivery/return'),
            'state': json.dumps(metadata),
        }
        return {
            'type': 'ir.actions.act_url',
            'url': f'{oauth_url}?{urls.url_encode(oauth_url_params)}',
            'target': 'self',
        }

    def authorization_jd_delivery(self, code):
        key, secret = self.get_jd_access_info()
        response = requests.get('{jd_url}/oauth/token'.format(jd_url=self.get_jd_url()), params={
            'code': code,
            'client_secret': secret,
            'client_id': key,
        })
        data = response.json()
        to_utc = lambda ds: fields.Datetime.from_string(ds) - relativedelta(hours=8)
        self.write({
            'jd_access_token': data['accessToken'],
            'jd_access_expire': to_utc(data['accessExpire']),
            'jd_refresh_token': data['refreshToken'],
            'jd_refresh_expire': to_utc(data['refreshExpire']),
        })
