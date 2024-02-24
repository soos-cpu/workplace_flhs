import json
import logging
import pprint
import hmac

from werkzeug.exceptions import Forbidden
from werkzeug.urls import url_encode, url_join
from werkzeug.utils import redirect

from odoo import http
from odoo.exceptions import ValidationError
from odoo.http import request
from odoo.tools import hmac as hmac_tool

_logger = logging.getLogger(__name__)


class JDDeliveryController(http.Controller):
    @http.route('/jd_delivery/return', type='http', methods=['GET'], auth='none')
    def jd_delivery_return_authorization(self, **data):
        if not data or not request.session.uid:
            return redirect('/web/login', 303)
        try:
            code = data['code']
            state = json.loads(data['state'])
        except Exception:
            return redirect('/web/login', 303)
        _logger.info("京东用户验证返回的数据:\n%s", pprint.pformat(data))
        delivery_carrier_id = state['delivery_carrier_id']
        received_signature = state['signature']
        expected_signature = hmac_tool(
            request.env(su=True), 'jd_delivery_compute_oauth_signature', str(delivery_carrier_id)
        )
        if not hmac.compare_digest(received_signature, expected_signature):
            _logger.warning("根据数据计算的签名与预期签名不匹配。")
            raise Forbidden()
        delivery_carrier = request.env(user=request.session.uid)['delivery.carrier'].browse(
            int(delivery_carrier_id)).exists()
        if not delivery_carrier_id:
            _logger.warning("未能找到对应的物流: %s" % delivery_carrier_id)
            raise Forbidden()
        delivery_carrier.authorization_jd_delivery(code)
        url = self._compute_delivery_carrier_url(delivery_carrier_id)
        return redirect(url)

    @staticmethod
    def _compute_delivery_carrier_url(delivery_carrier_id):
        action = request.env.ref('delivery.action_delivery_carrier_form', raise_if_not_found=False)
        get_params_string = url_encode({
            'id': delivery_carrier_id,
            'model': 'delivery.carrier',
            'view_type': 'form',
            'action': action and action.id,
        })
        return f'/web#{get_params_string}'
