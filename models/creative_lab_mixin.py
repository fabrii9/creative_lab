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

    _SUGGESTION_STYLE_PARAMS = {
        'image': 'creative_lab.suggest_image_instructions',
        'copy': 'creative_lab.suggest_copy_instructions',
        'ad': 'creative_lab.suggest_ad_instructions',
    }

    def _suggestion_style(self, kind):
        param = self._SUGGESTION_STYLE_PARAMS.get(kind)
        if not param:
            return ''
        value = self.env['ir.config_parameter'].sudo().get_param(param)
        return (value or '').strip()
