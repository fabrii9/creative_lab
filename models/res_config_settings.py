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
    creative_lab_suggest_image_instructions = fields.Char(
        string='Instrucciones para prompts de imagen',
        config_parameter='creative_lab.suggest_image_instructions',
        help=(
            'Se agregan a cada sugerencia del asistente Generar / retocar '
            '(campos Prompt y Evitar). Ejemplo: estilo visual de la marca, '
            'paleta, qué evitar siempre.'
        ),
    )
    creative_lab_suggest_copy_instructions = fields.Char(
        string='Instrucciones para copy del creativo',
        config_parameter='creative_lab.suggest_copy_instructions',
        help=(
            'Se agregan a cada sugerencia de titular, texto principal y '
            'llamado a la acción del creativo. Ejemplo: tono, palabras '
            'prohibidas, estructura preferida.'
        ),
    )
    creative_lab_suggest_ad_instructions = fields.Char(
        string='Instrucciones para copy del anuncio Meta',
        config_parameter='creative_lab.suggest_ad_instructions',
        help=(
            'Se agregan a cada sugerencia de título, descripción y texto '
            'principal de la publicación Meta.'
        ),
    )
