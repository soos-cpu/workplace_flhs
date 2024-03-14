# -*- coding: utf-8 -*-

from odoo import api, fields, models, registry, SUPERUSER_ID, _
from odoo.exceptions import ValidationError, UserError
from odoo.addons.delivery_jd_mix_rule.api.jd_api import JDApi


# 默認使用 快遞B2C-京東標快 （包裹重量小於30kg）
class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    delivery_type = fields.Selection(
        selection_add=[('jd_mix_rule', '基於規則的京東物流')],
        ondelete={'jd_mix_rule': lambda recs: recs.write({'delivery_type': 'base_on_rule'})}
    )

    def _is_available_for_order(self, order):
        res = super()._is_available_for_order(order)
        if res and self.delivery_type == 'jd_mix_rule':
            return self.rate_shipment(order).get('success')
        return res

    # ==========================================================================================

    @api.model
    def jd_mix_rule_config_params(self):
        icp_get = self.env['ir.config_parameter'].sudo().get_param
        res = [
            icp_get('delivery_jd_mix_rule.jd_mix_rule_app_key'),
            icp_get('delivery_jd_mix_rule.jd_mix_rule_app_secret'),
            icp_get('delivery_jd_mix_rule.jd_mix_rule_access_token'),
            icp_get('delivery_jd_mix_rule.jd_mix_rule_customer_code'),
        ]
        if not all(res):
            raise ValidationError(_("請在配置裡填寫必要信息"))
        return res

    def jd_mix_rule_new_api(self):
        params = self.jd_mix_rule_config_params()
        return JDApi(
            *params[:3], self.log_xml, prod_environment=self.prod_environment,
        ), params[-1]

    def jd_mix_rule_rate_shipment(self, order):
        # 先驗證是否支持京東物流
        api, customer_code = self.jd_mix_rule_new_api()
        try:
            pre_check_result = api.ecap_v1_orders_precheck([{
                "senderContact": {
                    "fullAddress": order.company_id.partner_id._display_address()
                },
                "receiverContact": {
                    "fullAddress": order.partner_shipping_id._display_address()
                },
                "orderOrigin": "1",
                "customerCode": customer_code,
                "productsReq": {
                    "productCode": "ed-m-0001",
                }
            }]).json()
        except Exception as e:
            pre_check_result = {}
        if not pre_check_result.get('success'):
            return {'success': False,
                    'price': 0.0,
                    'error_message': "地址不支持京東物流",
                    'warning_message': False}
        return self.base_on_rule_rate_shipment(order)

    def jd_mix_rule_send_shipping(self, pickings):
        bor_result = self.base_on_rule_send_shipping(pickings)
        api, customer_code = self.jd_mix_rule_new_api()
        for index, picking in enumerate(pickings):
            order = self.env['sale.order'].search([('name', '=', picking.origin)], limit=1)
            partner = order.partner_shipping_id or order.partner_id
            data = [{
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
                "orderOrigin": "1",
                "customerCode": customer_code,
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
            }]
            result = api.orders_create(data).json()
            if not result['success']:
                raise ValidationError(result['msg'])
            else:
                bor_result[index]['tracking_number'] = result['data']['waybillCode']
        return bor_result

    def jd_mix_rule_cancel_shipment(self, pickings):
        self = self.sudo()
        api, customer_code = self.jd_mix_rule_new_api()
        for picking in pickings:
            data = [{
                "waybillCode": picking.carrier_tracking_ref,
                "orderOrigin": "1",
                "customerCode": customer_code,
                "cancelReason": "用户发起取消",
                "cancelReasonCode": "1",
                "cancelType": 1
            }]
            result = api.orders_cancel(data).json()
            if not result['success']:
                raise ValidationError(result['subMsg'])

    def jd_mix_rule_get_tracking_link(self, picking):
        return 'https://www.jdl.com/orderSearch/?waybillCodes=%s' % picking.carrier_tracking_ref
