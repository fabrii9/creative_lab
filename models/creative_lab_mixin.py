# -*- coding: utf-8 -*-

from odoo import fields, models


class CreativeLabMixin(models.AbstractModel):
    _name = 'creative.lab.mixin'
    _description = 'Indicadores de configuración de Creative Lab'

    simple_mode = fields.Boolean(compute='_compute_simple_mode', compute_sudo=True)

    def _compute_simple_mode(self):
        enabled = self._simple_mode_enabled()
        for record in self:
            record.simple_mode = enabled

    def _simple_mode_enabled(self):
        value = self.env['ir.config_parameter'].sudo().get_param('creative_lab.simple_mode')
        return str(value).strip().lower() in ('1', 'true')
