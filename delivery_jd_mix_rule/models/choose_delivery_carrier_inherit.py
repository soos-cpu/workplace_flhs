# -*- coding: utf-8 -*-

from odoo import fields, models, api, _


class ChooseDeliveryCarrier(models.TransientModel):
    _inherit = 'choose.delivery.carrier'

    def _onchange_order_id(self):
        if self.delivery_type != 'jd_mix_rule':
            return super(ChooseDeliveryCarrier, self)._onchange_order_id()
