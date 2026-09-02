# -*- coding: utf-8 -*-

import json
import re
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from ..services.llm_bridge import CreativeLLMBridge


class CreativeAgentProfile(models.Model):
    _name = 'creative.agent.profile'
    _description = 'Perfil de agente creativo'
    _inherit = ['mail.thread']
    _order = 'sequence, id'
    _check_company_auto = True

    name = fields.Char(string='Nombre', required=True, tracking=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    role = fields.Selection(
        [
            ('strategist', 'Estratega de marketing'),
            ('creative_director', 'Director creativo'),
            ('image_generator', 'Generador visual'),
            ('variation', 'Generador de variaciones'),
            ('reviewer', 'Revisor'),
            ('analyst', 'Analista'),
        ],
        required=True,
        default='image_generator',
        tracking=True,
    )
    task_type = fields.Selection(
        [('text', 'Texto'), ('image', 'Imagen'), ('edit', 'Edición de imagen'), ('analysis', 'Análisis')],
        string='Tipo de tarea',
        required=True,
        default='image',
    )
    execution_mode = fields.Selection(
        [('simulation', 'Simulación local'), ('provider', 'Proveedor real')],
        string='Modo',
        required=True,
        default='simulation',
        tracking=True,
    )
    llm_provider_id = fields.Many2one(
        'llm.provider',
        string='Proveedor LLM',
        check_company=True,
        ondelete='restrict',
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        tracking=True,
        help='Las credenciales permanecen en LLM Connector.',
    )
    model_alias = fields.Char(
        string='Perfil lógico',
        help='Nombre estable como image_draft, vision_judge o reasoning_high.',
    )
    model_override = fields.Char(
        string='Modelo específico',
        help='Vacío utiliza el modelo configurado en LLM Connector.',
    )
    system_prompt = fields.Text(string='Instrucción del sistema', required=True)
    prompt_template = fields.Text(
        string='Plantilla de prompt',
        help='Puede usar {prompt}, {brief}, {hypothesis} y {creative}.',
    )
    output_format = fields.Selection(
        [('text', 'Texto'), ('json', 'JSON'), ('binary', 'Archivo')],
        default='binary',
        required=True,
    )
    output_schema = fields.Text(string='Esquema de salida JSON')
    temperature = fields.Float(default=0.4)
    max_tokens = fields.Integer(default=2048)
    timeout = fields.Integer(string='Timeout (s)', default=120)
    max_cost_usd = fields.Float(string='Costo máximo por ejecución', default=1.0)
    image_size = fields.Selection(
        [
            ('1024x1024', '1024 × 1024'),
            ('1024x1536', '1024 × 1536'),
            ('1536x1024', '1536 × 1024'),
        ],
        default='1024x1024',
    )

    @api.constrains('execution_mode', 'llm_provider_id')
    def _check_provider(self):
        for profile in self:
            if profile.execution_mode == 'provider' and not profile.llm_provider_id:
                raise ValidationError(_('Seleccioná un proveedor de LLM Connector para el modo real.'))
            if (
                profile.llm_provider_id.company_id
                and profile.llm_provider_id.company_id != profile.company_id
            ):
                raise ValidationError(_('El agente y el proveedor deben pertenecer a la misma compañía.'))


class CreativeAgentRun(models.Model):
    _name = 'creative.agent.run'
    _description = 'Ejecución de agente creativo'
    _inherit = ['mail.thread']
    _order = 'id desc'
    _check_company_auto = True

    _unique_idempotency = models.Constraint(
        'UNIQUE(idempotency_key)',
        'La clave de idempotencia ya fue utilizada.',
    )

    name = fields.Char(string='Ejecución', required=True, readonly=True, copy=False)
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    profile_id = fields.Many2one(
        'creative.agent.profile',
        string='Agente',
        required=True,
        check_company=True,
        ondelete='restrict',
        tracking=True,
    )
    task_type = fields.Selection(related='profile_id.task_type', store=True, readonly=True)
    brief_id = fields.Many2one('creative.brief', string='Brief', check_company=True, ondelete='set null')
    creative_id = fields.Many2one('creative.asset', string='Creativo', check_company=True, ondelete='set null')
    source_version_id = fields.Many2one(
        'creative.asset.version',
        string='Versión fuente',
        check_company=True,
        ondelete='restrict',
    )
    operation = fields.Selection(
        [
            ('strategy', 'Estrategia'),
            ('initial', 'Generación'),
            ('edit', 'Retoque'),
            ('variation', 'Variación'),
            ('review', 'Revisión'),
            ('analysis', 'Análisis'),
        ],
        required=True,
        default='initial',
    )
    input_prompt = fields.Text(string='Prompt', required=True, readonly=True)
    input_file = fields.Binary(string='Archivo de entrada', attachment=True, readonly=True, copy=False)
    input_filename = fields.Char(string='Nombre de entrada', readonly=True)
    input_mime_type = fields.Char(string='MIME de entrada', readonly=True)
    status = fields.Selection(
        [
            ('queued', 'En cola'),
            ('running', 'Ejecutando'),
            ('succeeded', 'Correcta'),
            ('failed', 'Fallida'),
            ('cancelled', 'Cancelada'),
        ],
        default='queued',
        required=True,
        readonly=True,
        tracking=True,
        index=True,
    )
    idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    attempt = fields.Integer(default=0, readonly=True)
    started_at = fields.Datetime(readonly=True)
    finished_at = fields.Datetime(readonly=True)
    duration_seconds = fields.Float(readonly=True)
    output_text = fields.Text(string='Respuesta', readonly=True, copy=False)
    output_json = fields.Json(string='JSON de salida', readonly=True, copy=False)
    output_file = fields.Binary(string='Archivo generado', attachment=True, readonly=True, copy=False)
    output_filename = fields.Char(readonly=True, copy=False)
    output_mime_type = fields.Char(readonly=True, copy=False)
    provider_snapshot = fields.Char(readonly=True, copy=False)
    model_snapshot = fields.Char(readonly=True, copy=False)
    external_request_id = fields.Char(readonly=True, copy=False)
    tokens_input = fields.Integer(readonly=True)
    tokens_output = fields.Integer(readonly=True)
    estimated_cost = fields.Float(digits=(12, 6), readonly=True)
    error_message = fields.Text(readonly=True, copy=False)
    result_version_id = fields.Many2one(
        'creative.asset.version',
        string='Versión resultante',
        readonly=True,
        copy=False,
        ondelete='restrict',
    )

    _immutable_input_fields = {
        'name', 'company_id', 'profile_id', 'brief_id', 'creative_id',
        'source_version_id', 'operation', 'input_prompt', 'input_file',
        'input_filename', 'input_mime_type', 'idempotency_key',
    }
    _managed_execution_fields = {
        'status', 'attempt', 'started_at', 'finished_at', 'duration_seconds',
        'output_text', 'output_json', 'output_file', 'output_filename',
        'output_mime_type', 'provider_snapshot', 'model_snapshot',
        'external_request_id', 'tokens_input', 'tokens_output',
        'estimated_cost', 'error_message', 'result_version_id',
    }

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for values in vals_list:
            vals = dict(values)
            provided_results = self._managed_execution_fields.intersection(vals) - {'status'}
            if provided_results or vals.get('status', 'queued') != 'queued':
                raise AccessError(_('Una ejecución nueva debe comenzar en cola y sin resultado.'))
            vals.setdefault('idempotency_key', str(uuid.uuid4()))
            vals.setdefault('name', _('Ejecución %s') % vals['idempotency_key'][:8])
            profile = self.env['creative.agent.profile'].browse(vals['profile_id']).exists()
            if profile:
                vals.setdefault('company_id', profile.company_id.id)
            prepared.append(vals)
        return super().create(prepared)

    def write(self, vals):
        if self._immutable_input_fields.intersection(vals):
            raise AccessError(_('La entrada de una ejecución auditada no puede modificarse.'))
        if (
            self._managed_execution_fields.intersection(vals)
            and not self.env.context.get('allow_execution_write')
        ):
            raise AccessError(_('El resultado de la ejecución solo puede escribirlo el motor de agentes.'))
        return super().write(vals)

    @api.constrains('brief_id', 'creative_id', 'source_version_id', 'company_id')
    def _check_targets(self):
        for run in self:
            if run.brief_id and run.brief_id.company_id != run.company_id:
                raise ValidationError(_('El brief no pertenece a la compañía de la ejecución.'))
            if run.creative_id and run.creative_id.company_id != run.company_id:
                raise ValidationError(_('El creativo no pertenece a la compañía de la ejecución.'))
            if run.source_version_id:
                if not run.creative_id or run.source_version_id.creative_id != run.creative_id:
                    raise ValidationError(_('La versión fuente debe pertenecer al creativo de la ejecución.'))

    def action_execute(self):
        for run in self:
            run._execute()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if all(run.status == 'succeeded' for run in self) else 'warning',
                'title': _('Ejecución finalizada'),
                'message': _('Revisá el resultado y el registro de auditoría.'),
                'sticky': False,
            },
        }

    def _execute(self):
        self.ensure_one()
        if self.status == 'succeeded':
            return
        started = fields.Datetime.now()
        self.with_context(allow_execution_write=True).write({
            'status': 'running',
            'started_at': started,
            'finished_at': False,
            'error_message': False,
            'attempt': self.attempt + 1,
        })
        try:
            result = CreativeLLMBridge(self.env).execute(self)
            finished = fields.Datetime.now()
            values = {
                'status': 'succeeded',
                'finished_at': finished,
                'duration_seconds': (finished - started).total_seconds(),
                'output_text': result.get('text'),
                'output_json': result.get('json'),
                'output_file': result.get('file'),
                'output_filename': result.get('filename'),
                'output_mime_type': result.get('mime_type'),
                'provider_snapshot': result.get('provider'),
                'model_snapshot': result.get('model'),
                'external_request_id': result.get('request_id'),
                'tokens_input': result.get('tokens_input', 0),
                'tokens_output': result.get('tokens_output', 0),
                'estimated_cost': result.get('cost', 0.0),
            }
            if self.profile_id.output_format == 'json' and result.get('text') and not result.get('json'):
                values['output_json'] = self._parse_json(result['text'])
            self.with_context(allow_execution_write=True).write(values)
        except Exception as exc:  # noqa: BLE001 - el fallo debe quedar auditado
            finished = fields.Datetime.now()
            self.with_context(allow_execution_write=True).write({
                'status': 'failed',
                'finished_at': finished,
                'duration_seconds': (finished - started).total_seconds(),
                'error_message': self._sanitize_error(exc),
            })

    def action_retry(self):
        for run in self:
            if run.status != 'failed':
                raise ValidationError(_('Solo se pueden reintentar ejecuciones fallidas.'))
            run._execute()

    def action_cancel(self):
        for run in self:
            if run.status not in ('queued', 'failed'):
                raise ValidationError(_('Solo se puede cancelar una ejecución en cola o fallida.'))
            run.with_context(allow_execution_write=True).write({'status': 'cancelled'})

    @api.model
    def _parse_json(self, text):
        cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.IGNORECASE)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValidationError(_('El agente no devolvió JSON válido.')) from exc

    def _sanitize_error(self, error):
        message = str(error)[:2000]
        provider = self.profile_id.llm_provider_id.sudo()
        if provider and provider.api_key:
            message = message.replace(provider.api_key, '***')
        message = re.sub(r'(Bearer\s+)[^\s]+', r'\1***', message, flags=re.IGNORECASE)
        return message
