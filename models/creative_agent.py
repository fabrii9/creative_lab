# -*- coding: utf-8 -*-

import json
import math
import re
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from ..services.llm_bridge import CreativeLLMBridge


def _reject_non_finite_json(constant):
    raise ValueError('JSON no finito: %s' % constant)


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
    max_cost_usd = fields.Float(
        string='Costo máximo por ejecución',
        default=1.0,
        digits=(12, 6),
        help=(
            'Límite duro para una ejecución real. El motor bloquea la llamada '
            'cuando la estimación conservadora supera este valor.'
        ),
    )
    input_cost_per_million = fields.Float(
        string='USD por millón de tokens de entrada',
        digits=(12, 6),
        help='Tarifa del modelo usada para estimar el costo antes de llamar al proveedor.',
    )
    output_cost_per_million = fields.Float(
        string='USD por millón de tokens de salida',
        digits=(12, 6),
        help='Tarifa del modelo usada con el máximo de tokens configurado.',
    )
    fixed_cost_usd = fields.Float(
        string='Costo fijo estimado USD',
        digits=(12, 6),
        help=(
            'Costo conservador adicional por ejecución. Para imágenes debe '
            'cubrir el precio de una imagen; para visión puede cubrir el input visual.'
        ),
    )
    image_size = fields.Selection(
        [
            ('1024x1024', '1024 × 1024'),
            ('1024x1536', '1024 × 1536'),
            ('1536x1024', '1536 × 1024'),
        ],
        default='1024x1024',
        help=(
            'Tamaño para modelos legacy y fallback. Los modelos gpt-image-2 '
            'derivan el tamaño de la relación de aspecto del creativo.'
        ),
    )
    image_quality = fields.Selection(
        [
            ('auto', 'Automática'),
            ('low', 'Baja'),
            ('medium', 'Media'),
            ('high', 'Alta'),
        ],
        string='Calidad de imagen',
        default='auto',
        required=True,
        help='Se envía a modelos gpt-image; los modelos legacy la ignoran.',
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

    @api.constrains(
        'execution_mode',
        'max_cost_usd',
        'input_cost_per_million',
        'output_cost_per_million',
        'fixed_cost_usd',
    )
    def _check_cost_configuration(self):
        for profile in self:
            prices = (
                profile.max_cost_usd,
                profile.input_cost_per_million,
                profile.output_cost_per_million,
                profile.fixed_cost_usd,
            )
            if any(price < 0 for price in prices):
                raise ValidationError(_('Los límites y precios de costo no pueden ser negativos.'))
            if profile.execution_mode == 'provider' and not profile.max_cost_usd:
                raise ValidationError(_(
                    'Definí un costo máximo mayor que cero para usar un proveedor real.'
                ))

    @api.constrains('output_format', 'output_schema')
    def _check_output_schema(self):
        for profile in self:
            if not profile.output_schema:
                continue
            if profile.output_format != 'json':
                raise ValidationError(_(
                    'El esquema de salida solo se puede usar con el formato JSON.'
                ))
            try:
                schema = json.loads(
                    profile.output_schema,
                    parse_constant=_reject_non_finite_json,
                )
            except (TypeError, ValueError) as exc:
                raise ValidationError(_('El esquema de salida no contiene JSON válido.')) from exc
            if not isinstance(schema, (dict, list)):
                raise ValidationError(_(
                    'El esquema de salida debe ser un objeto o una lista JSON.'
                ))


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
        accounted_cost = 0.0
        self.with_context(allow_execution_write=True).write({
            'status': 'running',
            'started_at': started,
            'finished_at': False,
            'error_message': False,
            'attempt': self.attempt + 1,
        })
        try:
            accounted_cost = self._check_preflight_cost()
            result = CreativeLLMBridge(self.env).execute(self)
            finished = fields.Datetime.now()
            output_json = result.get('json')
            if self.profile_id.output_format == 'json':
                if output_json is None:
                    if not result.get('text'):
                        raise ValidationError(_('El agente no devolvió una salida JSON.'))
                    output_json = self._parse_json(result['text'])
                self._validate_finite_json(output_json)
                self._validate_output_schema(output_json)

            if 'cost' in result and result.get('cost') is not None:
                reported_cost = float(result['cost'])
                if not math.isfinite(reported_cost) or reported_cost < 0:
                    self._check_reported_cost(reported_cost)
                accounted_cost = max(accounted_cost, reported_cost)
            self._check_reported_cost(accounted_cost)
            values = {
                'status': 'succeeded',
                'finished_at': finished,
                'duration_seconds': (finished - started).total_seconds(),
                'output_text': result.get('text'),
                'output_json': output_json,
                'output_file': result.get('file'),
                'output_filename': result.get('filename'),
                'output_mime_type': result.get('mime_type'),
                'provider_snapshot': result.get('provider'),
                'model_snapshot': result.get('model'),
                'external_request_id': result.get('request_id'),
                'tokens_input': result.get('tokens_input', 0),
                'tokens_output': result.get('tokens_output', 0),
                'estimated_cost': accounted_cost,
            }
            self.with_context(allow_execution_write=True).write(values)
        except Exception as exc:  # noqa: BLE001 - el fallo debe quedar auditado
            finished = fields.Datetime.now()
            self.with_context(allow_execution_write=True).write({
                'status': 'failed',
                'finished_at': finished,
                'duration_seconds': (finished - started).total_seconds(),
                'estimated_cost': accounted_cost,
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
            return json.loads(cleaned, parse_constant=_reject_non_finite_json)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_('El agente no devolvió JSON válido.')) from exc

    def _check_preflight_cost(self):
        """Block unpriced or over-budget provider calls before they spend money."""
        self.ensure_one()
        profile = self.profile_id
        if profile.execution_mode == 'simulation':
            return 0.0
        if not any((
            profile.input_cost_per_million,
            profile.output_cost_per_million,
            profile.fixed_cost_usd,
        )):
            raise ValidationError(_(
                'Configurá las tarifas del modelo o un costo fijo estimado antes '
                'de ejecutar este agente con un proveedor real.'
            ))

        uses_paid_media = profile.task_type in ('image', 'edit') or bool(
            self.input_file or self.source_version_id.file
        )
        if uses_paid_media and profile.fixed_cost_usd <= 0:
            raise ValidationError(_(
                'Configurá un costo fijo conservador para generar, editar o '
                'analizar una imagen antes de llamar al proveedor.'
            ))

        prompt = CreativeLLMBridge(self.env)._render_prompt(self)
        system_prompt = profile.system_prompt or ''
        # Three characters per token is a deliberately conservative estimate
        # for Spanish prompts, without coupling this module to a tokenizer.
        estimated_input_tokens = max(1, math.ceil((len(prompt) + len(system_prompt)) / 3))
        estimated_cost = (
            profile.fixed_cost_usd
            + (estimated_input_tokens * profile.input_cost_per_million / 1_000_000)
            + (profile.max_tokens * profile.output_cost_per_million / 1_000_000)
        )
        self._check_reported_cost(estimated_cost)
        return estimated_cost

    def _check_reported_cost(self, cost):
        self.ensure_one()
        if self.profile_id.execution_mode == 'simulation':
            return
        maximum = self.profile_id.max_cost_usd
        if not math.isfinite(cost) or cost < 0:
            raise ValidationError(_('El proveedor informó un costo inválido.'))
        if maximum <= 0:
            raise ValidationError(_(
                'El agente no tiene un costo máximo válido configurado.'
            ))
        if cost > maximum:
            raise ValidationError(_(
                'La ejecución fue bloqueada porque su costo estimado '
                '(%(cost).6f USD) supera el máximo del agente (%(maximum).6f USD).'
            ) % {'cost': cost, 'maximum': maximum})

    def _validate_output_schema(self, payload):
        """Validate JSON against either a JSON Schema subset or an example shape.

        Existing profiles store an example document as their schema. Profiles
        may also use the common JSON Schema keywords ``type``, ``properties``,
        ``required``, ``items``, ``enum`` and ``additionalProperties``.
        """
        self.ensure_one()
        raw_schema = self.profile_id.output_schema
        if not raw_schema:
            return
        try:
            schema = json.loads(raw_schema, parse_constant=_reject_non_finite_json)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_('El esquema configurado no contiene JSON válido.')) from exc
        if self._looks_like_json_schema(schema):
            self._validate_json_schema_value(payload, schema, '$')
        else:
            self._validate_example_schema_value(payload, schema, '$')

    @api.model
    def _looks_like_json_schema(self, schema):
        if not isinstance(schema, dict):
            return False
        if any(key in schema for key in (
            '$schema', 'properties', 'required', 'items', 'enum',
            'additionalProperties', 'minItems', 'maxItems',
        )):
            return True
        schema_type = schema.get('type')
        valid_types = {'object', 'array', 'string', 'number', 'integer', 'boolean', 'null'}
        if isinstance(schema_type, str):
            return schema_type in valid_types
        if isinstance(schema_type, list) and schema_type:
            return all(item in valid_types for item in schema_type)
        return False

    @api.model
    def _validate_finite_json(self, value, path='$'):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValidationError(_(
                'La salida JSON no cumple el estándar: %(path)s no puede ser NaN o infinito.'
            ) % {'path': path})
        if isinstance(value, dict):
            for key, child in value.items():
                self._validate_finite_json(child, '%s.%s' % (path, key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                self._validate_finite_json(child, '%s[%s]' % (path, index))

    @api.model
    def _validate_example_schema_value(self, value, schema, path):
        if isinstance(schema, dict):
            if not isinstance(value, dict):
                self._schema_error(path, _('un objeto'))
            for key, child_schema in schema.items():
                if key not in value:
                    raise ValidationError(_(
                        'La salida JSON no cumple el esquema: falta %(path)s.'
                    ) % {'path': '%s.%s' % (path, key)})
                self._validate_example_schema_value(
                    value[key], child_schema, '%s.%s' % (path, key)
                )
            return
        if isinstance(schema, list):
            if not isinstance(value, list):
                self._schema_error(path, _('una lista'))
            if schema:
                if not value:
                    raise ValidationError(_(
                        'La salida JSON no cumple el esquema: %(path)s debe '
                        'contener al menos un elemento.'
                    ) % {'path': path})
                for index, item in enumerate(value):
                    self._validate_example_schema_value(item, schema[0], '%s[%s]' % (path, index))
            return
        if isinstance(schema, str):
            if not isinstance(value, str):
                self._schema_error(path, _('un texto'))
            allowed = [item.strip() for item in schema.split('|') if item.strip()]
            if len(allowed) > 1 and value not in allowed:
                raise ValidationError(_(
                    'La salida JSON no cumple el esquema: %(path)s debe ser uno '
                    'de estos valores: %(allowed)s.'
                ) % {'path': path, 'allowed': ', '.join(allowed)})
            return
        if isinstance(schema, bool):
            if not isinstance(value, bool):
                self._schema_error(path, _('un booleano'))
            return
        if isinstance(schema, (int, float)) and not isinstance(schema, bool):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                self._schema_error(path, _('un número'))
            return
        if schema is None and value is not None:
            self._schema_error(path, _('un valor nulo'))

    @api.model
    def _validate_json_schema_value(self, value, schema, path):
        if schema is True:
            return
        if schema is False:
            raise ValidationError(_(
                'La salida JSON no cumple el esquema: %(path)s no admite ningún valor.'
            ) % {'path': path})
        if not isinstance(schema, dict):
            raise ValidationError(_(
                'El esquema JSON configurado es inválido en %(path)s.'
            ) % {'path': path})
        if 'enum' in schema and value not in schema['enum']:
            raise ValidationError(_(
                'La salida JSON no cumple el esquema: %(path)s tiene un valor no permitido.'
            ) % {'path': path})
        schema_type = schema.get('type')
        expected_types = schema_type if isinstance(schema_type, list) else [schema_type]
        type_matches = {
            'object': lambda item: isinstance(item, dict),
            'array': lambda item: isinstance(item, list),
            'string': lambda item: isinstance(item, str),
            'number': lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
            'integer': lambda item: isinstance(item, int) and not isinstance(item, bool),
            'boolean': lambda item: isinstance(item, bool),
            'null': lambda item: item is None,
        }
        if schema_type is not None:
            if not expected_types or any(item not in type_matches for item in expected_types):
                raise ValidationError(_(
                    'El esquema JSON configurado contiene un tipo desconocido en %(path)s.'
                ) % {'path': path})
        known_types = [item for item in expected_types if item in type_matches]
        if known_types and not any(type_matches[item](value) for item in known_types):
            self._schema_error(path, ' / '.join(known_types))
        if isinstance(value, dict):
            properties = schema.get('properties') or {}
            for key in schema.get('required') or []:
                if key not in value:
                    raise ValidationError(_(
                        'La salida JSON no cumple el esquema: falta %(path)s.'
                    ) % {'path': '%s.%s' % (path, key)})
            for key, child_schema in properties.items():
                if key in value:
                    self._validate_json_schema_value(
                        value[key], child_schema, '%s.%s' % (path, key)
                    )
            if schema.get('additionalProperties') is False:
                extra = set(value) - set(properties)
                if extra:
                    raise ValidationError(_(
                        'La salida JSON no cumple el esquema: %(path)s contiene '
                        'claves no permitidas: %(keys)s.'
                    ) % {'path': path, 'keys': ', '.join(sorted(extra))})
        if isinstance(value, list):
            if len(value) < schema.get('minItems', 0):
                raise ValidationError(_(
                    'La salida JSON no cumple el esquema: %(path)s contiene '
                    'menos elementos que los requeridos.'
                ) % {'path': path})
            if 'maxItems' in schema and len(value) > schema['maxItems']:
                raise ValidationError(_(
                    'La salida JSON no cumple el esquema: %(path)s contiene '
                    'más elementos que los permitidos.'
                ) % {'path': path})
            if schema.get('items'):
                for index, item in enumerate(value):
                    self._validate_json_schema_value(
                        item, schema['items'], '%s[%s]' % (path, index)
                    )

    @api.model
    def _schema_error(self, path, expected):
        raise ValidationError(_(
            'La salida JSON no cumple el esquema: %(path)s debe ser %(expected)s.'
        ) % {'path': path, 'expected': expected})

    def _sanitize_error(self, error):
        message = str(error)[:2000]
        provider = self.profile_id.llm_provider_id.sudo()
        if provider and provider.api_key:
            message = message.replace(provider.api_key, '***')
        message = re.sub(r'(Bearer\s+)[^\s]+', r'\1***', message, flags=re.IGNORECASE)
        return message
