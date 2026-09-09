# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    creative_lab_simple_mode = fields.Boolean(
        string='Modo simple (operador único)',
        config_parameter='creative_lab.simple_mode',
        help=(
            'Simplifica el flujo para una sola persona: las versiones nuevas '
            'se aprueban automáticamente, el simulador queda oculto en el '
            'asistente de generación y la preparación y creación de la '
            'campaña en Meta se fusionan en un solo paso.'
        ),
    )
