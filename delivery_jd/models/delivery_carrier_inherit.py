# -*- coding: utf-8 -*-

from odoo import api, fields, models, registry, SUPERUSER_ID, _
from odoo.exceptions import ValidationError
from odoo.tools.misc import hmac as hmac_tool
from odoo.addons.delivery_jd.api.jd_api import JDApi
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
    customer_code = fields.Char(string="客户编码")
    business_unit_code = fields.Char(string="事业部编码")

    @api.model
    def get_jd_access_info(self):
        result = self.env['res.config.settings'].get_jd_access_info()
        if not all(result):
            raise ValidationError(_("请在库存-配置-设置-物流对接-京东物流连接器里填写密钥"))
        return result

    def get_jd_oauth_url(self):
        return 'https://oauth.jdl.com' if self.prod_environment else 'https://uat-oauth.jdl.com'

    def get_jd_api_url(self):
        return 'https://api.jdl.com' if self.prod_environment else 'https://uat-api.jdl.com'

    def action_oauth_jd_delivery(self):
        self.ensure_one()
        oauth_url = "{jd_url}/oauth/authorize".format(jd_url=self.get_jd_oauth_url())
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
        response = requests.get('{jd_url}/oauth/token'.format(jd_url=self.get_jd_oauth_url()), params={
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

    def jd_rate_shipment(self, order):
        self = self.sudo()
        pickings = order.picking_ids.filtered(lambda p: p.state == 'done')
        if not pickings:
            return {'price': 0, 'success': False, 'error_message': _('京东物流还未发货')}
        elif not pickings[0].carrier_tracking_ref:
            return {'price': 0, 'success': False, 'error_message': _('京东物流单号有误')}
        else:
            api = JDApi(
                *self.get_jd_access_info(), self.jd_access_token, base_uri=self.get_jd_api_url()
            )
            result = api.orders_actualfee_query([{
                "waybillCode": pickings[0].carrier_tracking_ref,
                "orderOrigin": 1,
                "customerCode": self.customer_code
            }]).json()
            if not result['success']:
                return {'price': 0, 'success': False, 'error_message': result['msg']}
            else:
                return {'price': result['data']['sumMoney'], 'success': True}

    def jd_send_shipping(self, picking):
        """
        :param picking: 这里源码传递的是pickings 但是只取了返回的第一个值说明这个变量只有一条记录
        :return:
        """
        self = self.sudo()
        api = JDApi(
            *self.get_jd_access_info(), self.jd_access_token, base_uri=self.get_jd_api_url()
        )
        order = self.env['sale.order'].search([('name', '=', picking.origin)], limit=1)
        if not order:
            raise ValidationError(_('请核对源单据订单是否存在'))
        partner = order.partner_shipping_id or order.partner_id
        val = {
            "orderId": picking.origin,
            "senderContact": {
                "name": self.env.company.name,
                "mobile": self.env.company.mobile,
                "phone": self.env.company.phone,
                "fullAddress": self.env.company.partner_id._display_address()
            },
            "receiverContact": {
                "name": partner.name,
                "mobile": partner.mobile,
                "phone": partner.phone,
                "fullAddress": partner._display_address()
            },
            "orderOrigin": 1,
            "customerCode": self.customer_code,
            "productsReq": {
                "productCode": "ed-m-0001",
            },
            "settleType": "3",
            "cargoes": [
                {
                    "name": order.order_line[0].product_id.name,
                    "quantity": 1,
                    "weight": 1,
                    "volume": 10,
                }
            ],
            "CommonChannelInfo": {
                "channelCode": "0030001"
            }
        }
        data = [val]
        result = api.orders_create(data).json()
        if not result['success']:
            raise ValidationError(result['msg'])
        else:
            return [{
                'exact_price': result['data'].get('freightPre') or 0,
                'tracking_number': result['data']['waybillCode'],
            }]

    def jd_cancel_shipment(self, pickings):
        self = self.sudo()
        api = JDApi(
            *self.get_jd_access_info(), self.jd_access_token, base_uri=self.get_jd_api_url()
        )
        for picking in pickings:
            data = [{
                "waybillCode": picking.carrier_tracking_ref,
                "orderOrigin": 1,
                "customerCode": self.customer_code,
                "cancelReason": "用户发起取消",
                "cancelReasonCode": "1",
                "cancelType": 1
            }]
            result = api.orders_cancel(data).json()
            if not result['success']:
                raise ValidationError(result['subMsg'])

    def jd_get_tracking_link(self, picking):
        return 'https://www.jdl.com/orderSearch/?waybillCodes=%s' % picking.carrier_tracking_ref

    def jd_get_default_custom_package_code(self):
        return 'Delivery JD'
