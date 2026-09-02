# -*- coding: utf-8 -*-

import mimetypes

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CreativeAgentRunWizard(models.TransientModel):
    _name = 'creative.agent.run.wizard'
    _description = 'Ejecutar un agente sobre un brief o creativo'

    brief_id = fields.Many2one('creative.brief', string='Brief', required=True, readonly=True)
    creative_id = fields.Many2one(
        'creative.asset',
        string='Creativo',
        domain="[('brief_id', '=', brief_id)]",
        readonly=True,
    )
    source_version_id = fields.Many2one(
        'creative.asset.version',
        string='Versión a analizar',
        domain="[('creative_id', '=', creative_id)]",
    )
    company_id = fields.Many2one(related='brief_id.company_id', readonly=True)
    profile_id = fields.Many2one(
        'creative.agent.profile',
        string='Agente',
        required=True,
        domain="[('company_id', '=', company_id), ('task_type', 'in', ['text', 'analysis']), ('active', '=', True)]",
    )
    operation = fields.Selection(
        [
            ('strategy', 'Estrategia'),
            ('review', 'Revisión'),
            ('analysis', 'Análisis'),
            ('variation', 'Variaciones de copy'),
        ],
        required=True,
        default='strategy',
    )
    prompt = fields.Text(string='Pedido', required=True)
    input_file = fields.Binary(string='Archivo adicional', attachment=False)
    input_filename = fields.Char(string='Nombre del archivo')

    @api.onchange('creative_id')
    def _onchange_creative_id(self):
        if self.creative_id and not self.source_version_id:
            self.source_version_id = self.creative_id.current_version_id

    def action_run(self):
        self.ensure_one()
        if self.creative_id and self.creative_id.brief_id != self.brief_id:
            raise ValidationError(_('El creativo no pertenece al brief.'))
        if self.source_version_id and self.source_version_id.creative_id != self.creative_id:
            raise ValidationError(_('La versión no pertenece al creativo.'))
        if self.profile_id.task_type not in ('text', 'analysis'):
            raise ValidationError(_('Seleccioná un agente de texto o análisis.'))
        run = self.env['creative.agent.run'].create({
            'profile_id': self.profile_id.id,
            'company_id': self.company_id.id,
            'brief_id': self.brief_id.id,
            'creative_id': self.creative_id.id,
            'source_version_id': self.source_version_id.id,
            'operation': self.operation,
            'input_prompt': self.prompt,
            'input_file': self.input_file,
            'input_filename': self.input_filename,
            'input_mime_type': (
                mimetypes.guess_type(self.input_filename)[0]
                if self.input_filename else False
            ),
        })
        run._execute()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Resultado del agente'),
            'res_model': 'creative.agent.run',
            'res_id': run.id,
            'view_mode': 'form',
            'target': 'current',
        }
