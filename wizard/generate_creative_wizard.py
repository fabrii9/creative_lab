# -*- coding: utf-8 -*-

import base64
import hashlib
import mimetypes
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..services.llm_bridge import CreativeLLMBridge


class CreativeGenerateWizard(models.TransientModel):
    _name = 'creative.generate.wizard'
    _description = 'Generar, importar o retocar un creativo'
    _inherit = 'creative.lab.mixin'

    TARGET_ASPECT_RATIOS = ('1:1', '9:16')

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
    generate_all_formats = fields.Boolean(
        string='Generar también en cuadrado y vertical',
        default=True,
        help='Además del formato de este creativo, genera la misma pieza en '
             '1:1 y 9:16 como creativos hermanos con el mismo prompt y copy. '
             'Cada formato es una ejecución de agente con su propio costo.',
    )
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

        run = self._run_image_generation(self.creative_id, self.operation, self.source_version_id)
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

        version = self._version_from_run(self.creative_id, self.operation, run, self.source_version_id)
        if self.generate_all_formats:
            self._generate_sibling_formats()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Versión generada'),
            'res_model': 'creative.asset.version',
            'res_id': version.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _run_image_generation(self, creative, operation, source_version):
        effective_prompt = self.prompt
        if self.negative_prompt:
            effective_prompt = '%s\n\n%s: %s' % (
                effective_prompt,
                _('Evitar'),
                self.negative_prompt,
            )
        run = self.env['creative.agent.run'].create({
            'profile_id': self.agent_profile_id.id,
            'company_id': creative.company_id.id,
            'brief_id': creative.brief_id.id,
            'creative_id': creative.id,
            'source_version_id': source_version.id if source_version else False,
            'operation': operation,
            'input_prompt': effective_prompt,
            'input_file': self.input_file,
            'input_filename': self.input_filename,
            'input_mime_type': self._guess_input_mime(),
        })
        creative._system_write({'state': 'generating'})
        run._execute()
        return run

    def _version_from_run(self, creative, operation, run, source_version):
        source_sha = source_version.sha256 if source_version else False
        if self.input_file:
            source_sha = hashlib.sha256(base64.b64decode(self.input_file)).hexdigest()
        version = self.env['creative.asset.version'].create({
            'creative_id': creative.id,
            'parent_id': source_version.id if source_version else False,
            'operation': operation,
            'prompt': self.prompt,
            'negative_prompt': self.negative_prompt,
            'source_filename': self.input_filename or (
                source_version.filename if source_version else False
            ),
            'source_sha256': source_sha,
            'file': run.output_file,
            'filename': run.output_filename,
            'mime_type': run.output_mime_type,
            'agent_profile_id': self.agent_profile_id.id,
            'agent_run_id': run.id,
            'provider_snapshot': run.provider_snapshot,
            'model_snapshot': run.model_snapshot,
            'parameters_json': {
                'operation': operation,
                'temperature': self.agent_profile_id.temperature,
                'max_tokens': self.agent_profile_id.max_tokens,
                'image_size': self.agent_profile_id.image_size,
                'image_quality': self.agent_profile_id.image_quality,
                'aspect_ratio': creative.aspect_ratio,
            },
            'external_request_id': run.external_request_id,
            'estimated_cost': run.estimated_cost,
        })
        run._system_write({'result_version_id': version.id})
        return version

    def _generate_sibling_formats(self):
        failures = []
        for ratio in self.TARGET_ASPECT_RATIOS:
            if ratio == self.creative_id.aspect_ratio:
                continue
            sibling = self._find_or_create_sibling(ratio)
            operation = self.operation
            source = sibling.current_version_id
            if operation == 'initial' or (not source and not self.input_file):
                operation = 'initial'
                source = self.env['creative.asset.version'].browse()
            run = self._run_image_generation(sibling, operation, source)
            if run.status != 'succeeded' or not run.output_file:
                failures.append('%s: %s' % (
                    sibling.name,
                    run.error_message or _('el agente no devolvió una imagen.'),
                ))
                continue
            self._version_from_run(sibling, operation, run, source)
        if failures:
            self.creative_id.message_post(
                body=_('Formatos alternativos que no se pudieron generar: %s')
                % '; '.join(failures),
                message_type='comment',
            )

    def _find_or_create_sibling(self, aspect_ratio):
        creative = self.creative_id
        base_name = re.sub(r'\s*·\s*[^·]*\d+:\d+\s*$', '', creative.name)
        sibling = self.env['creative.asset'].search([
            ('brief_id', '=', creative.brief_id.id),
            ('hypothesis_id', '=', creative.hypothesis_id.id),
            ('aspect_ratio', '=', aspect_ratio),
            ('name', 'ilike', base_name),
        ], limit=1)
        if sibling:
            return sibling
        return self.env['creative.asset'].create({
            'name': '%s · %s' % (base_name, aspect_ratio),
            'brief_id': creative.brief_id.id,
            'hypothesis_id': creative.hypothesis_id.id,
            'owner_id': creative.owner_id.id,
            'asset_type': creative.asset_type,
            'aspect_ratio': aspect_ratio,
            'placement': 'story' if aspect_ratio == '9:16' else 'feed',
            'headline': creative.headline,
            'primary_text': creative.primary_text,
            'call_to_action': creative.call_to_action,
        })

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
        return self.creative_id._suggest_text(goal, draft)

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
        self._validate_source_mime()

    def _validate_source_mime(self):
        if self.operation not in ('edit', 'variation'):
            return
        if self.agent_profile_id.execution_mode != 'provider':
            return
        if self.input_file:
            source_mime = self._guess_input_mime()
        else:
            source_mime = self.source_version_id.mime_type
        if source_mime and source_mime not in CreativeLLMBridge.SUPPORTED_EDIT_MIMES:
            raise ValidationError(_(
                'La imagen fuente (%(mime)s) no la admiten los proveedores: '
                'solo PNG, JPEG o WebP. Si es una versión vieja del simulador '
                'en SVG, generá una base nueva (el simulador ahora produce '
                'PNG) o importá un archivo raster como fuente.'
            ) % {'mime': source_mime})

    def _guess_input_mime(self):
        if not self.input_filename:
            return False
        return mimetypes.guess_type(self.input_filename)[0] or 'application/octet-stream'
