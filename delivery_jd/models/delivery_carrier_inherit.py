# -*- coding: utf-8 -*-

from odoo import api, fields, models, registry, SUPERUSER_ID, _
from odoo.exceptions import ValidationError, UserError
from odoo.tools.misc import hmac as hmac_tool
from odoo.tools import float_compare, float_round
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
    jd_customer_code = fields.Char(string="客户编码")
    jd_business_unit_code = fields.Char(string="事业部编码")
    # https://cloud.jdl.com/#/open-business-document/access-guide/267/54152
    jd_order_origin = fields.Selection(selection=[('1', '快递B2C'), ('4', '快运B2C')], string="下单来源", default='1')
    # https://cloud.jdl.com/#/open-business-document/access-guide/267/54153
    jd_main_product_code = fields.Selection(selection=[('ed-m-0001', '京东标快'), ('ed-m-0002', '京东特快')],
                                            string="主产品编码")
    jd_default_package_type_id = fields.Many2one('stock.package.type', string='京东默认包裹类型')

    @api.model
    def get_jd_access_info(self):
        result = self.env['res.config.settings'].get_jd_access_info()
        if not all(result):
            raise ValidationError(_("请在库存-配置-设置-物流对接-京东物流连接器里填写密钥"))
        return result

    def get_jd_oauth_url(self):
        return 'https://oauth.jdl.com' if self.prod_environment else 'https://uat-oauth.jdl.com'

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

    def jd_new_api(self):
        return JDApi(
            *self.get_jd_access_info(), self.jd_access_token, self.log_xml, prod_environment=self.prod_environment,
        )

    @api.model
    def jd_compute_order_weight_volume(self, order):
        weight_in_kg, volume_in_cm3 = 0.0, 0.0
        for line in order.order_line.filtered(lambda l: l.product_id.type in ['product',
                                                                              'consu'] and not l.is_delivery and not l.display_type and l.product_uom_qty > 0):
            qty = line.product_uom._compute_quantity(line.product_uom_qty, line.product_id.uom_id)
            weight_in_kg += (line.product_id.weight or 0.0) * qty
            volume_in_cm3 += (line.product_id.volume or 0.0) * qty * 10 ** 6
        return weight_in_kg, volume_in_cm3

    def jd_common_check_pre_create_order(self, api, order):
        if order.order_line and all(order.order_line.mapped(lambda l: l.product_id.type == 'service')):
            return "因为你的所有产品都是服务，所以无法计算出估计的运输价格。"
        if not order.order_line:
            return "请至少提供一个发货项目"
        error_lines = order.order_line.filtered(
            lambda line: (not line.product_id.weight
                          and not line.is_delivery
                          and line.product_id.type != 'service'
                          and not line.display_type))
        if error_lines:
            return "因为缺少以下产品的重量，所以无法计算出估计的运输价格。\n%s" % ", ".join(
                error_lines.product_id.mapped('name'))
        return False

    def jd_rate_shipment(self, order):
        self = self.sudo()
        api = self.jd_new_api()
        msg = self.jd_common_check_pre_create_order(api, order)
        if msg:
            return {'success': False,
                    'price': 0.0,
                    'error_message': msg,
                    'warning_message': False}
        try:
            weight_in_kg, volume_in_cm3 = self.jd_compute_order_weight_volume(order)
            precheck_result = api.ecap_v1_orders_precheck([{
                "senderContact": {
                    "fullAddress": order.company_id.partner_id._display_address()
                },
                "receiverContact": {
                    "fullAddress": order.partner_shipping_id._display_address()
                },
                "orderOrigin": self.jd_order_origin,
                "customerCode": self.jd_customer_code,
                "businessUnitCode": self.jd_business_unit_code,
                "cargoes": [{
                    "weight": float_round(weight_in_kg, precision_digits=2, rounding_method='UP'),
                    "volume": float_round(volume_in_cm3, precision_digits=2, rounding_method='UP')
                }],
                "productsReq": {
                    "productCode": self.jd_main_product_code,
                }
            }]).json()
            if not precheck_result.get('success'):
                return precheck_result.get('msg') or '失败'
            price = precheck_result['data']['totalFreightStandard']
        except UserError as e:
            return {'success': False,
                    'price': 0.0,
                    'error_message': e.args[0],
                    'warning_message': False}
        if order.currency_id.name != 'CNY':
            quote_currency = self.env['res.currency'].search([('name', '=', 'CNY')], limit=1)
            price = quote_currency._convert(price, order.currency_id, order.company_id,
                                            order.date_order or fields.Date.today())
        return {'success': True,
                'price': price,
                'error_message': False,
                'warning_message': False}

    def jd_send_shipping(self, picking):
        """
        :param picking: 这里源码传递的是pickings 但是只取了返回的第一个值说明这个变量只有一条记录
        :return:
        """
        self = self.sudo()
        api = self.jd_new_api()
        order = self.env['sale.order'].search([('name', '=', picking.origin)], limit=1)
        if not order:
            raise ValidationError(_('请核对源单据订单是否存在'))
        partner = order.partner_shipping_id or order.partner_id
        weight_in_kg, volume_in_cm3 = self.jd_compute_order_weight_volume(order)
        product_line = order.order_line.filtered(
            lambda line: line.product_id.type != 'service' and line.product_uom_qty
        )[0]
        val = {
            "orderId": picking.origin,
            "senderContact": {
                "name": order.company_id.name,
                "mobile": order.company_id.mobile,
                "phone": order.company_id.phone,
                "fullAddress": order.company_id.partner_id._display_address()
            },
            "receiverContact": {
                "name": partner.name,
                "mobile": partner.mobile,
                "phone": partner.phone,
                "fullAddress": partner._display_address()
            },
            "orderOrigin": self.jd_order_origin,
            "customerCode": self.jd_customer_code,
            "businessUnitCode": self.jd_business_unit_code,
            "productsReq": {
                "productCode": self.jd_main_product_code,
            },
            "settleType": "3",
            "cargoes": [
                {
                    "name": product_line.product_id.name,
                    "quantity": product_line.product_uom_qty,
                    "weight": float_round(weight_in_kg, precision_digits=2, rounding_method='UP'),
                    "volume": float_round(volume_in_cm3, precision_digits=2, rounding_method='UP')
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
        api = self.jd_new_api()
        for picking in pickings:
            data = [{
                "waybillCode": picking.carrier_tracking_ref,
                "orderOrigin": self.jd_order_origin,
                "customerCode": self.jd_customer_code,
                "businessUnitCode": self.jd_business_unit_code,
                "cancelReason": "用户发起取消",
                "cancelReasonCode": "1",
                "cancelType": 1
            }]
            result = api.orders_cancel(data).json()
            if not result['success']:
                raise ValidationError(result['subMsg'])

    def jd_get_tracking_link(self, picking):
        return 'https://www.jdl.com/orderSearch/?waybillCodes=%s' % picking.carrier_tracking_ref

    # 默认b2c业务
    def jd_get_default_custom_package_code(self):
        return 'b2c'

    # 暂时没有C2B业务
    # 通常是指从C端揽收送往B端，一般简称C2B业务。例如：图书回收、洗护业务、电商平台客户退货发起的逆向业务等业务场景
    @api.model
    def jd_get_return_label(self, pickings, tracking_number=None, origin_date=None):
        return ''
