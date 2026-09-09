# -*- coding: utf-8 -*-

import base64
import hashlib
import mimetypes

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class CreativeGenerateWizard(models.TransientModel):
    _name = 'creative.generate.wizard'
    _description = 'Generar, importar o retocar un creativo'
    _inherit = 'creative.lab.mixin'

    creative_id = fields.Many2one('creative.asset', required=True, readonly=True)
    company_id = fields.Many2one(related='creative_id.company_id', readonly=True)
    operation = fields.Selection(
        [
            ('initial', 'Generación inicial'),
            ('import', 'Importar archivo'),
            ('edit', 'Retocar versión'),
            ('variation', 'Crear variación'),
        ],
        required=True,
        default='initial',
    )
    source_version_id = fields.Many2one(
        'creative.asset.version',
        string='Versión fuente',
        domain="[('creative_id', '=', creative_id)]",
    )
    agent_profile_id = fields.Many2one(
        'creative.agent.profile',
        string='Agente',
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
    )
    prompt = fields.Text(string='Prompt o instrucción')
    negative_prompt = fields.Text(string='Evitar')
    input_file = fields.Binary(string='Archivo fuente', attachment=False)
    input_filename = fields.Char(string='Nombre del archivo')
    allowed_agent_profile_ids = fields.Many2many(
        'creative.agent.profile',
        compute='_compute_allowed_agent_profile_ids',
        compute_sudo=True,
    )

    @api.depends('creative_id')
    def _compute_allowed_agent_profile_ids(self):
        for wizard in self:
            profiles = self.env['creative.agent.profile'].search([
                ('company_id', '=', wizard.company_id.id),
                ('active', '=', True),
            ])
            if wizard.simple_mode:
                real_profiles = profiles.filtered(lambda item: item.execution_mode != 'simulation')
                profiles = real_profiles or profiles
            wizard.allowed_agent_profile_ids = profiles

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        creative_id = values.get('creative_id') or self.env.context.get('default_creative_id')
        creative = self.env['creative.asset'].browse(creative_id).exists()
        if (
            creative
            and not values.get('source_version_id')
            and creative.brief_id.initial_file
            and 'input_file' in fields_list
        ):
            values['input_file'] = creative.brief_id.initial_file
            values['input_filename'] = creative.brief_id.initial_filename
        return values

    @api.onchange('creative_id')
    def _onchange_creative_id(self):
        if self.creative_id and not self.source_version_id:
            self.source_version_id = self.creative_id.current_version_id

    @api.onchange('operation')
    def _onchange_operation(self):
        if self.operation == 'initial':
            self.source_version_id = False

    def action_generate(self):
        self.ensure_one()
        self._validate_request()
        if self.operation == 'import':
            return self._create_imported_version()

        effective_prompt = self.prompt
        if self.negative_prompt:
            effective_prompt = '%s\n\n%s: %s' % (
                effective_prompt,
                _('Evitar'),
                self.negative_prompt,
            )
        run = self.env['creative.agent.run'].create({
            'profile_id': self.agent_profile_id.id,
            'company_id': self.company_id.id,
            'brief_id': self.creative_id.brief_id.id,
            'creative_id': self.creative_id.id,
            'source_version_id': self.source_version_id.id,
            'operation': self.operation,
            'input_prompt': effective_prompt,
            'input_file': self.input_file,
            'input_filename': self.input_filename,
            'input_mime_type': self._guess_input_mime(),
        })
        self.creative_id._system_write({'state': 'generating'})
        run._execute()
        if run.status != 'succeeded':
            return {
                'type': 'ir.actions.act_window',
                'name': _('Ejecución fallida'),
                'res_model': 'creative.agent.run',
                'res_id': run.id,
                'view_mode': 'form',
                'target': 'current',
            }
        if not run.output_file:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Resultado del agente'),
                'res_model': 'creative.agent.run',
                'res_id': run.id,
                'view_mode': 'form',
                'target': 'current',
            }

        source_sha = self.source_version_id.sha256
        if self.input_file:
            source_sha = hashlib.sha256(base64.b64decode(self.input_file)).hexdigest()
        version = self.env['creative.asset.version'].create({
            'creative_id': self.creative_id.id,
            'parent_id': self.source_version_id.id,
            'operation': self.operation,
            'prompt': self.prompt,
            'negative_prompt': self.negative_prompt,
            'source_filename': self.input_filename or self.source_version_id.filename,
            'source_sha256': source_sha,
            'file': run.output_file,
            'filename': run.output_filename,
            'mime_type': run.output_mime_type,
            'agent_profile_id': self.agent_profile_id.id,
            'agent_run_id': run.id,
            'provider_snapshot': run.provider_snapshot,
            'model_snapshot': run.model_snapshot,
            'parameters_json': {
                'operation': self.operation,
                'temperature': self.agent_profile_id.temperature,
                'max_tokens': self.agent_profile_id.max_tokens,
                'image_size': self.agent_profile_id.image_size,
                'image_quality': self.agent_profile_id.image_quality,
                'aspect_ratio': self.creative_id.aspect_ratio,
            },
            'external_request_id': run.external_request_id,
            'estimated_cost': run.estimated_cost,
        })
        run._system_write({'result_version_id': version.id})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Versión generada'),
            'res_model': 'creative.asset.version',
            'res_id': version.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_suggest_prompt(self):
        self.ensure_one()
        if self.operation in ('edit', 'variation'):
            goal = _(
                'Redactá la instrucción de retoque para editar la imagen fuente '
                'con un modelo de imágenes. Sé específico sobre qué cambiar y '
                'qué conservar. No agregues explicaciones ni comillas.'
            )
        else:
            goal = _(
                'Redactá un prompt de generación de imagen listo para usarse en '
                'un modelo de imágenes. Incluí sujeto, estilo, composición, '
                'ambiente y relación de aspecto. No agregues explicaciones ni comillas.'
            )
        self.prompt = self._run_suggestion(goal, self.prompt)

    def action_suggest_negative_prompt(self):
        self.ensure_one()
        goal = _(
            'Listá en una sola línea, separados por comas, los elementos que el '
            'modelo de imágenes debe evitar en esta pieza: errores frecuentes, '
            'elementos fuera de marca y todo lo que baje la calidad. '
            'No agregues explicaciones ni comillas.'
        )
        self.negative_prompt = self._run_suggestion(goal, self.negative_prompt)

    def _run_suggestion(self, goal, draft):
        profile = self._get_suggestion_profile()
        instruction = goal
        if draft:
            instruction = '%s\n\n%s:\n%s' % (
                instruction,
                _('Mejorá y completá este borrador del usuario'),
                draft,
            )
        context = self._suggestion_context()
        if context:
            instruction = '%s\n\n%s:\n%s' % (instruction, _('Contexto'), context)
        run = self.env['creative.agent.run'].create({
            'profile_id': profile.id,
            'company_id': self.company_id.id,
            'brief_id': self.creative_id.brief_id.id,
            'creative_id': self.creative_id.id,
            'operation': 'strategy',
            'input_prompt': instruction,
        })
        run._execute()
        if run.status != 'succeeded' or not run.output_text:
            raise ValidationError(
                _('La sugerencia falló: %s')
                % (run.error_message or _('el agente no devolvió texto.'))
            )
        return run.output_text.strip()

    def _get_suggestion_profile(self):
        profiles = self.env['creative.agent.profile'].search([
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
            ('task_type', '=', 'text'),
        ])
        if not profiles:
            raise ValidationError(_(
                'No hay ningún agente de texto configurado. Crealo en '
                'Creative Lab > Configuración > Agentes con tipo de tarea Texto.'
            ))
        real_profiles = profiles.filtered(lambda item: item.execution_mode != 'simulation')
        candidates = real_profiles or profiles
        director = candidates.filtered(lambda item: item.role == 'creative_director')
        return (director or candidates)[0]

    def _suggestion_context(self):
        creative = self.creative_id
        brief = creative.brief_id
        hypothesis = creative.hypothesis_id
        lines = []
        for label, value in (
            (_('Objetivo'), brief.objective),
            (_('Oferta'), brief.offer),
            (_('Público'), brief.target_audience),
            (_('Ángulo de la hipótesis'), hypothesis.angle),
            (_('Hook de la hipótesis'), hypothesis.hook),
            (_('Titular del creativo'), creative.headline),
            (_('Texto principal del creativo'), creative.primary_text),
        ):
            if value:
                lines.append('%s: %s' % (label, value))
        if creative.aspect_ratio or creative.placement:
            lines.append('%s: %s / %s' % (
                _('Formato'),
                creative.aspect_ratio or '-',
                creative.placement or '-',
            ))
        return '\n'.join(lines)

    def _create_imported_version(self):
        raw = base64.b64decode(self.input_file)
        version = self.env['creative.asset.version'].create({
            'creative_id': self.creative_id.id,
            'parent_id': self.source_version_id.id,
            'operation': 'import',
            'prompt': self.prompt or _('Archivo importado manualmente'),
            'source_filename': self.input_filename,
            'source_sha256': hashlib.sha256(raw).hexdigest(),
            'file': self.input_file,
            'filename': self.input_filename,
            'mime_type': self._guess_input_mime(),
            'provider_snapshot': 'manual',
            'model_snapshot': 'manual-import',
            'parameters_json': {'operation': 'import'},
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Versión importada'),
            'res_model': 'creative.asset.version',
            'res_id': version.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _validate_request(self):
        if self.operation == 'import':
            if not self.input_file or not self.input_filename:
                raise ValidationError(_('Seleccioná un archivo para importar.'))
            mime_type = self._guess_input_mime()
            if mime_type not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif'):
                raise ValidationError(_('La importación manual admite PNG, JPEG, WebP o GIF.'))
            try:
                raw = base64.b64decode(self.input_file)
            except Exception as exc:
                raise ValidationError(_('El archivo importado no contiene base64 válido.')) from exc
            width, height = self.env['creative.asset.version']._image_dimensions(raw)
            if not width or not height:
                raise ValidationError(_('El archivo importado no es una imagen válida.'))
            return
        if not self.agent_profile_id:
            raise ValidationError(_('Seleccioná un agente.'))
        if self.agent_profile_id.task_type not in ('image', 'edit'):
            raise ValidationError(_('Este asistente solo admite agentes de imagen o edición.'))
        if not self.prompt:
            raise ValidationError(_('Escribí un prompt o instrucción.'))
        if self.operation in ('edit', 'variation') and not (
            self.source_version_id or self.input_file
        ):
            raise ValidationError(_('Un retoque o variación necesita una versión o archivo fuente.'))
        if self.source_version_id and self.source_version_id.creative_id != self.creative_id:
            raise ValidationError(_('La versión fuente no pertenece al creativo.'))

    def _guess_input_mime(self):
        if not self.input_filename:
            return False
        return mimetypes.guess_type(self.input_filename)[0] or 'application/octet-stream'
