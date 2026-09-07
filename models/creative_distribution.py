# -*- coding: utf-8 -*-

import base64
import hashlib
import io
import json
import math
import uuid
from datetime import datetime, timedelta, timezone

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from ..services.meta_ads import MetaAdsError

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


class CreativeAssetExport(models.Model):
    _name = 'creative.asset.export'
    _description = 'Exportación de activo creativo'
    _inherit = ['mail.thread']
    _order = 'id desc'
    _check_company_auto = True

    _unique_fingerprint = models.Constraint(
        'UNIQUE(fingerprint)',
        'Esta versión ya fue exportada con el mismo preset.',
    )

    name = fields.Char(string='Exportación', required=True, readonly=True, copy=False)
    version_id = fields.Many2one(
        'creative.asset.version',
        string='Versión',
        required=True,
        check_company=True,
        ondelete='restrict',
        index=True,
        readonly=True,
    )
    creative_id = fields.Many2one(
        related='version_id.creative_id',
        store=True,
        readonly=True,
        index=True,
    )
    company_id = fields.Many2one(
        related='version_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    file = fields.Binary(string='Archivo final', required=True, attachment=True, readonly=True, copy=False)
    filename = fields.Char(string='Nombre del archivo', required=True, readonly=True)
    mime_type = fields.Char(string='Tipo MIME', readonly=True)
    sha256 = fields.Char(string='SHA-256', required=True, readonly=True, copy=False)
    file_size = fields.Integer(string='Tamaño', readonly=True)
    output_format = fields.Selection(
        [('original', 'Original'), ('png', 'PNG'), ('jpeg', 'JPEG'), ('webp', 'WebP')],
        required=True,
        readonly=True,
    )
    quality = fields.Integer(readonly=True)
    metadata_removed = fields.Boolean(readonly=True)
    fingerprint = fields.Char(required=True, readonly=True, copy=False, index=True)
    created_by_id = fields.Many2one(
        'res.users',
        string='Exportado por',
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
    )
    created_at = fields.Datetime(
        string='Exportado el',
        required=True,
        default=fields.Datetime.now,
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(_('Las exportaciones solo se materializan desde el asistente de limpieza.'))

    @api.model_create_multi
    def _create_materialized(self, vals_list):
        prepared = []
        for incoming in vals_list:
            vals = dict(incoming)
            version = self.env['creative.asset.version'].browse(vals['version_id']).exists()
            if not version or version.state != 'approved':
                raise ValidationError(_('Solo se puede materializar un export desde una versión aprobada.'))
            raw = base64.b64decode(vals.get('file') or b'')
            if not raw:
                raise ValidationError(_('El archivo exportado está vacío.'))
            vals['sha256'] = hashlib.sha256(raw).hexdigest()
            vals['file_size'] = len(raw)
            vals.setdefault('name', _('Export %s') % version.name)
            if vals.get('metadata_removed') and vals.get('mime_type') in ('image/png', 'image/jpeg'):
                self._verify_raster_metadata(raw)
            prepared.append(vals)
        return super().create(prepared)

    @api.model
    def _verify_raster_metadata(self, raw):
        if not Image:
            raise ValidationError(_('Pillow es obligatorio para verificar la limpieza de metadatos.'))
        try:
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
                exif = image.getexif()
                sensitive_keys = {
                    str(key).lower() for key in image.info
                    if str(key).lower() in ('exif', 'xmp', 'xml:com.adobe.xmp')
                }
                if exif or sensitive_keys:
                    raise ValidationError(_(
                        'El archivo todavía contiene EXIF/XMP y no puede marcarse como limpio.'
                    ))
        except ValidationError:
            raise
        except Exception as error:
            raise ValidationError(_('No se pudo verificar el archivo exportado.')) from error

    def write(self, vals):
        immutable = set(vals) - {'message_follower_ids', 'message_partner_ids'}
        if immutable:
            raise UserError(_('Las exportaciones son inmutables. Creá un nuevo preset si necesitás otro archivo.'))
        return super().write(vals)

    def unlink(self):
        raise UserError(_('Las exportaciones no se eliminan porque prueban qué archivo fue distribuido.'))

    def action_download(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/creative.asset.export/%s/file/%s?download=true' % (
                self.id,
                self.filename,
            ),
            'target': 'self',
        }


class CreativePublication(models.Model):
    _name = 'creative.publication'
    _description = 'Publicación de creativo'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _check_company_auto = True

    _REMOTE_STEP_SPECS = {
        'campaign': ('campaigns', 'external_campaign_id', 'Campaña'),
        'adset': ('adsets', 'external_adset_id', 'Conjunto'),
        'creative': ('adcreatives', 'external_creative_id', 'Creativo'),
        'ad': ('ads', 'external_ad_id', 'Anuncio'),
    }

    _SYSTEM_FIELDS = {
        'status', 'meta_account_id', 'external_image_hash', 'external_campaign_id',
        'external_adset_id', 'external_ad_id', 'external_creative_id',
        'remote_configured_status', 'remote_effective_status', 'remote_issues_json',
        'publish_step', 'publish_error', 'last_publish_at', 'reconcile_required',
        'reconcile_mode', 'delivery_pending', 'idempotency_key',
        'last_sync_at', 'last_sync_attempt_at', 'sync_error', 'metrics_json',
        'ad_currency_id',
        'spend', 'impressions', 'reach', 'clicks', 'inline_link_clicks',
        'meta_conversation_count', 'ctr', 'cpc', 'cpm', 'frequency',
    }
    _SNAPSHOT_FIELDS = {
        'name', 'platform', 'creative_id', 'version_id', 'export_id',
        'meta_connection_id', 'campaign_objective',
        'optimization_goal', 'billing_event', 'destination_type', 'special_ad_category',
        'targeting_json', 'primary_text', 'headline', 'description', 'welcome_message',
        'budget_type', 'daily_budget', 'lifetime_budget', 'start_at', 'end_at',
    }

    name = fields.Char(string='Publicación', required=True, tracking=True)
    creative_id = fields.Many2one(
        'creative.asset',
        string='Creativo',
        required=True,
        check_company=True,
        ondelete='restrict',
        tracking=True,
        index=True,
    )
    version_id = fields.Many2one(
        'creative.asset.version',
        string='Versión publicada',
        required=True,
        check_company=True,
        ondelete='restrict',
        tracking=True,
    )
    export_id = fields.Many2one(
        'creative.asset.export',
        string='Archivo final',
        check_company=True,
        ondelete='restrict',
        tracking=True,
    )
    company_id = fields.Many2one(
        related='creative_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    meta_connection_id = fields.Many2one(
        'creative.meta.account',
        string='Conexión Meta',
        check_company=True,
        ondelete='restrict',
        tracking=True,
    )
    ad_currency_id = fields.Many2one(
        'res.currency',
        string='Moneda publicitaria',
        compute='_compute_ad_currency',
        store=True,
        readonly=True,
    )
    platform = fields.Selection([('meta', 'Meta Ads')], default='meta', required=True)
    status = fields.Selection(
        [
            ('draft', 'Borrador'),
            ('prepared', 'Preparada'),
            ('paused', 'Pausada'),
            ('active', 'Activa'),
            ('error', 'Error'),
            ('archived', 'Archivada'),
        ],
        default='draft',
        required=True,
        tracking=True,
        index=True,
    )
    idempotency_key = fields.Char(
        string='Clave idempotente', default=lambda self: uuid.uuid4().hex,
        readonly=True, copy=False, index=True,
    )
    campaign_objective = fields.Selection(
        [('OUTCOME_LEADS', 'Clientes potenciales · WhatsApp')],
        default='OUTCOME_LEADS', required=True,
    )
    optimization_goal = fields.Selection(
        [('CONVERSATIONS', 'Conversaciones')], default='CONVERSATIONS', required=True,
    )
    billing_event = fields.Selection(
        [('IMPRESSIONS', 'Impresiones')], default='IMPRESSIONS', required=True,
    )
    destination_type = fields.Selection(
        [('WHATSAPP', 'WhatsApp')], default='WHATSAPP', required=True,
    )
    special_ad_category = fields.Selection([
        ('NONE', 'Ninguna'),
        ('CREDIT', 'Crédito'),
        ('EMPLOYMENT', 'Empleo'),
        ('HOUSING', 'Vivienda'),
        ('FINANCIAL_PRODUCTS_SERVICES', 'Productos financieros'),
        ('ISSUES_ELECTIONS_POLITICS', 'Temas sociales, elecciones o política'),
    ], default='NONE', required=True)
    targeting_json = fields.Text(
        string='Segmentación',
        required=True,
        default=(
            '{"geo_locations":{"countries":["AR"]},"age_min":18,"age_max":65,'
            '"targeting_automation":{"advantage_audience":0}}'
        ),
        help='JSON de targeting aceptado por Meta. Debe incluir geo_locations.',
    )
    primary_text = fields.Text(string='Texto principal')
    headline = fields.Char(string='Título')
    description = fields.Char(string='Descripción')
    welcome_message = fields.Char(
        string='Mensaje sugerido',
        default='Hola, quiero más información',
        required=True,
    )
    meta_account_id = fields.Char(string='Ad Account ID', readonly=True, copy=False)
    external_image_hash = fields.Char(string='Image Hash', readonly=True, copy=False)
    external_campaign_id = fields.Char(
        string='Campaign ID', index=True, readonly=True, copy=False,
    )
    external_adset_id = fields.Char(
        string='Ad Set ID', index=True, readonly=True, copy=False,
    )
    external_ad_id = fields.Char(string='Ad ID', index=True, readonly=True, copy=False)
    external_creative_id = fields.Char(
        string='Ad Creative ID', index=True, readonly=True, copy=False,
    )
    destination_phone = fields.Char(
        string='WhatsApp destino',
        related='meta_connection_id.whatsapp_phone_number',
        readonly=True,
    )
    budget_type = fields.Selection(
        [('daily', 'Diario'), ('lifetime', 'Total')],
        default='lifetime',
        required=True,
    )
    daily_budget = fields.Monetary(
        string='Presupuesto diario', currency_field='ad_currency_id',
    )
    lifetime_budget = fields.Monetary(
        string='Presupuesto total', currency_field='ad_currency_id',
    )
    start_at = fields.Datetime(string='Inicio')
    end_at = fields.Datetime(string='Fin')
    publish_step = fields.Selection([
        ('none', 'Sin iniciar'),
        ('image', 'Imagen'),
        ('campaign', 'Campaña'),
        ('adset', 'Conjunto'),
        ('creative', 'Creativo'),
        ('ad', 'Anuncio'),
        ('done', 'Completa'),
    ], default='none', readonly=True, copy=False)
    publish_error = fields.Text(string='Error de publicación', readonly=True, copy=False)
    last_publish_at = fields.Datetime(string='Publicado en Meta el', readonly=True, copy=False)
    reconcile_required = fields.Boolean(
        string='Requiere conciliación', readonly=True, copy=False,
        help='Una escritura tuvo respuesta incierta. Verificá Meta antes de reintentar.',
    )
    reconcile_mode = fields.Selection([
        ('publish', 'Creación remota'),
        ('delivery', 'Estado de entrega'),
    ], string='Tipo de conciliación', readonly=True, copy=False)
    delivery_pending = fields.Boolean(
        string='Cambio de entrega en cola', readonly=True, copy=False,
        help='Existe una orden durable pendiente de activar la jerarquía en Meta.',
    )
    remote_configured_status = fields.Char(
        string='Estado configurado', readonly=True, copy=False,
    )
    remote_effective_status = fields.Char(
        string='Estado efectivo', readonly=True, copy=False,
    )
    remote_issues_json = fields.Json(
        string='Problemas de entrega', readonly=True, copy=False,
    )
    last_sync_at = fields.Datetime(string='Última sincronización', readonly=True)
    last_sync_attempt_at = fields.Datetime(string='Último intento', readonly=True)
    sync_error = fields.Text(string='Error de sincronización', readonly=True)
    sync_enabled = fields.Boolean(string='Sincronización automática', default=True)

    spend = fields.Monetary(
        string='Gasto Meta', currency_field='ad_currency_id', default=0.0, readonly=True,
    )
    impressions = fields.Integer(default=0, readonly=True)
    reach = fields.Integer(default=0, readonly=True)
    clicks = fields.Integer(default=0, readonly=True)
    inline_link_clicks = fields.Integer(string='Clics en enlace', default=0, readonly=True)
    meta_conversation_count = fields.Float(string='Conversaciones según Meta', readonly=True)
    ctr = fields.Float(string='CTR', readonly=True, digits=(16, 4))
    cpc = fields.Monetary(string='CPC', currency_field='ad_currency_id', readonly=True)
    cpm = fields.Monetary(string='CPM', currency_field='ad_currency_id', readonly=True)
    frequency = fields.Float(string='Frecuencia', readonly=True, digits=(16, 4))
    metrics_json = fields.Json(string='Respuesta agregada', readonly=True, copy=False)
    metric_ids = fields.One2many(
        'creative.meta.metric.day', 'publication_id', string='Serie diaria',
    )
    operation_ids = fields.One2many(
        'creative.meta.operation', 'publication_id', string='Operaciones Meta',
    )
    outcome_ids = fields.One2many('creative.outcome', 'publication_id', string='Resultados')
    conversation_count = fields.Integer(compute='_compute_outcomes', store=True)
    qualified_count = fields.Integer(compute='_compute_outcomes', store=True)
    meeting_count = fields.Integer(compute='_compute_outcomes', store=True)
    sale_count = fields.Integer(compute='_compute_outcomes', store=True)
    attributed_revenue = fields.Monetary(compute='_compute_outcomes', store=True)
    cost_per_conversation = fields.Monetary(
        compute='_compute_unit_costs', currency_field='ad_currency_id',
    )
    cost_per_qualified = fields.Monetary(
        compute='_compute_unit_costs', currency_field='ad_currency_id',
    )
    cost_per_sale = fields.Monetary(
        compute='_compute_unit_costs', currency_field='ad_currency_id',
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('status', 'draft') != 'draft':
                raise AccessError(_('Las publicaciones deben iniciar como borrador.'))
            forbidden = self._SYSTEM_FIELDS.intersection(vals) - {'status'}
            if forbidden:
                raise AccessError(_('Los campos de Meta y métricas solo los actualiza el sistema.'))
        return super().create(vals_list)

    def write(self, vals):
        if self._SYSTEM_FIELDS.intersection(vals):
            raise AccessError(_('Usá las acciones de Creative Lab para modificar estados, IDs o métricas.'))
        if self._SNAPSHOT_FIELDS.intersection(vals) and any(
            publication.status != 'draft' or publication.external_campaign_id
            for publication in self
        ):
            raise ValidationError(_(
                'La configuración queda congelada al preparar. Duplicá la publicación para cambiarla.'
            ))
        return super().write(vals)

    def copy(self, default=None):
        self.ensure_one()
        values = super().copy_data(default=default)[0]
        for field_name in self._SYSTEM_FIELDS:
            values.pop(field_name, None)
        return self.create(values)

    def unlink(self):
        if any(
            publication.status != 'draft'
            or publication.external_campaign_id
            or publication.external_adset_id
            or publication.external_ad_id
            for publication in self
        ):
            raise UserError(_(
                'Una publicación preparada o enviada a Meta no se elimina; archivala para conservar la auditoría.'
            ))
        return super().unlink()

    def _system_write(self, vals):
        return super(CreativePublication, self).write(vals)

    @api.depends('meta_connection_id.currency_id', 'company_id.currency_id')
    def _compute_ad_currency(self):
        for publication in self:
            publication.ad_currency_id = (
                publication.meta_connection_id.currency_id or publication.company_id.currency_id
            )

    @api.depends('outcome_ids.event_type', 'outcome_ids.amount', 'outcome_ids.confirmed')
    def _compute_outcomes(self):
        for publication in self:
            confirmed = publication.outcome_ids.filtered('confirmed')
            publication.conversation_count = len(confirmed.filtered(lambda item: item.event_type == 'conversation'))
            publication.qualified_count = len(confirmed.filtered(lambda item: item.event_type == 'qualified'))
            publication.meeting_count = len(confirmed.filtered(lambda item: item.event_type == 'meeting_held'))
            sales = confirmed.filtered(lambda item: item.event_type == 'sale')
            publication.sale_count = len(sales)
            publication.attributed_revenue = sum(sales.mapped('amount'))

    @api.depends('spend', 'conversation_count', 'qualified_count', 'sale_count')
    def _compute_unit_costs(self):
        for publication in self:
            publication.cost_per_conversation = (
                publication.spend / publication.conversation_count
                if publication.conversation_count else 0.0
            )
            publication.cost_per_qualified = (
                publication.spend / publication.qualified_count
                if publication.qualified_count else 0.0
            )
            publication.cost_per_sale = (
                publication.spend / publication.sale_count
                if publication.sale_count else 0.0
            )

    @api.constrains('creative_id', 'version_id', 'export_id')
    def _check_version(self):
        for publication in self:
            if publication.version_id.creative_id != publication.creative_id:
                raise ValidationError(_('La versión publicada debe pertenecer al creativo.'))
            if publication.export_id and publication.export_id.version_id != publication.version_id:
                raise ValidationError(_('El archivo final debe pertenecer a la versión publicada.'))

    @api.constrains('daily_budget', 'lifetime_budget', 'start_at', 'end_at')
    def _check_budget_dates(self):
        for publication in self:
            if publication.daily_budget < 0 or publication.lifetime_budget < 0:
                raise ValidationError(_('Los presupuestos no pueden ser negativos.'))
            if publication.start_at and publication.end_at and publication.end_at <= publication.start_at:
                raise ValidationError(_('La fecha final debe ser posterior al inicio.'))

    def _check_publisher_access(self):
        if not self.env.user.has_group('creative_lab.grupo_creative_meta_publicador'):
            raise AccessError(_('Solo un publicador de Meta puede ejecutar esta acción.'))

    def _check_activator_access(self):
        if not self.env.user.has_group('creative_lab.grupo_creative_meta_activador'):
            raise AccessError(_('Solo un activador de Meta puede iniciar o detener gasto.'))

    @staticmethod
    def _json_object(value, label):
        try:
            parsed = json.loads(value or '{}')
        except (TypeError, ValueError):
            raise ValidationError(_('%s debe ser JSON válido.') % label) from None
        if not isinstance(parsed, dict):
            raise ValidationError(_('%s debe ser un objeto JSON.') % label)
        return parsed

    def _validate_for_meta(self):
        self.ensure_one()
        connection = self.meta_connection_id
        if self.version_id.state != 'approved':
            raise ValidationError(_('La versión debe estar aprobada.'))
        if not self.export_id or self.export_id.version_id != self.version_id:
            raise ValidationError(_('Elegí un archivo final de la misma versión.'))
        if not self.export_id.metadata_removed:
            raise ValidationError(_('El archivo final debe tener los metadatos eliminados.'))
        if self.export_id.mime_type not in ('image/png', 'image/jpeg'):
            raise ValidationError(_('Meta admite en este flujo únicamente exportaciones PNG o JPEG.'))
        if not self.export_id.sha256:
            raise ValidationError(_('El archivo final no tiene huella SHA-256.'))
        try:
            export_raw = base64.b64decode(self.export_id.file or b'')
        except Exception as error:
            raise ValidationError(_('El archivo final no contiene base64 válido.')) from error
        if not export_raw or hashlib.sha256(export_raw).hexdigest() != self.export_id.sha256:
            raise ValidationError(_('La huella del archivo final no coincide con su contenido.'))
        if len(export_raw) > 30 * 1024 * 1024:
            raise ValidationError(_('La imagen final supera el máximo de 30 MB admitido por este flujo.'))
        self.export_id._verify_raster_metadata(export_raw)
        if not connection or not connection.active:
            raise ValidationError(_('Elegí una conexión Meta activa.'))
        if connection.connection_state != 'ready' or not connection.currency_id:
            raise ValidationError(_('Probá la conexión Meta antes de preparar la publicación.'))
        targeting = self._json_object(self.targeting_json, _('La segmentación'))
        geo_locations = targeting.get('geo_locations')
        if not isinstance(geo_locations, dict):
            raise ValidationError(_('La segmentación debe incluir geo_locations.'))
        if not any(geo_locations.get(key) for key in (
            'countries', 'regions', 'cities', 'zips', 'custom_locations'
        )):
            raise ValidationError(_('geo_locations debe contener al menos una ubicación.'))
        phone = ''.join(
            character for character in (connection.whatsapp_phone_number or '')
            if character.isdigit()
        )
        if len(phone) < 8:
            raise ValidationError(_('Configurá el WhatsApp con código de país.'))
        if not (self.primary_text or '').strip() or not (self.headline or '').strip():
            raise ValidationError(_('Completá texto principal y título.'))
        if not (self.welcome_message or '').strip():
            raise ValidationError(_('Completá el mensaje sugerido de WhatsApp.'))
        if self.budget_type == 'daily':
            amount = self.daily_budget
            cap = connection.max_daily_budget
            label = _('presupuesto diario')
        else:
            amount = self.lifetime_budget
            cap = connection.max_lifetime_budget
            label = _('presupuesto total')
        if not self.end_at:
            raise ValidationError(_('Toda publicación Meta requiere una fecha final.'))
        if amount <= 0:
            raise ValidationError(_('El %s debe ser mayor que cero.') % label)
        if cap <= 0:
            raise ValidationError(_('Definí un tope de %s en la conexión Meta.') % label)
        if amount > cap:
            raise ValidationError(_('El %s supera el tope de la conexión Meta.') % label)
        start = self.start_at or fields.Datetime.now()
        if self.end_at <= start:
            raise ValidationError(_('La fecha final debe ser futura y posterior al inicio.'))
        if self.end_at > start + timedelta(days=connection.max_campaign_days):
            raise ValidationError(_('La duración supera el máximo permitido por la conexión.'))
        if self.budget_type == 'daily':
            if connection.max_lifetime_budget <= 0:
                raise ValidationError(_(
                    'Definí también un tope total en la conexión para limitar la exposición del presupuesto diario.'
                ))
            campaign_days = max(1, math.ceil((self.end_at - start).total_seconds() / 86400))
            projected = self.daily_budget * campaign_days
            if projected > connection.max_lifetime_budget:
                raise ValidationError(_(
                    'El máximo proyectado (%s × %s días) supera el tope total de la conexión.'
                ) % (self.daily_budget, campaign_days))
        return targeting, phone

    def _minor_units(self, amount):
        digits = self.ad_currency_id.decimal_places if self.ad_currency_id else 2
        return int(round(amount * (10 ** digits)))

    @staticmethod
    def _meta_datetime(value):
        moment = fields.Datetime.to_datetime(value)
        if not moment:
            return False
        return moment.replace(tzinfo=timezone.utc).isoformat()

    def _meta_name(self, suffix):
        key = self.idempotency_key or 'legacy-%s' % self.id
        return ('CL-%s · %s · %s' % (key, self.name, suffix))[:100]

    def _campaign_payload(self):
        categories = [] if self.special_ad_category == 'NONE' else [self.special_ad_category]
        return {
            'name': self._meta_name('Campaña'),
            'objective': self.campaign_objective,
            'buying_type': 'AUCTION',
            'special_ad_categories': categories,
            'status': 'PAUSED',
        }

    def _adset_payload(self, targeting, phone):
        connection = self.meta_connection_id
        promoted = {
            'page_id': connection.page_id,
            # Meta's promoted_object expects the international number without
            # formatting characters. Odoo keeps the human-readable +E.164 form.
            'whatsapp_phone_number': phone,
        }
        values = {
            'name': self._meta_name('Conjunto'),
            'campaign_id': self.external_campaign_id,
            'billing_event': self.billing_event,
            'optimization_goal': self.optimization_goal,
            'bid_strategy': 'LOWEST_COST_WITHOUT_CAP',
            'destination_type': self.destination_type,
            'promoted_object': promoted,
            'targeting': targeting,
            'status': 'PAUSED',
        }
        if self.budget_type == 'daily':
            values['daily_budget'] = self._minor_units(self.daily_budget)
        else:
            values['lifetime_budget'] = self._minor_units(self.lifetime_budget)
        if self.start_at:
            values['start_time'] = self._meta_datetime(self.start_at)
        if self.end_at:
            values['end_time'] = self._meta_datetime(self.end_at)
        return values

    def _creative_payload(self):
        connection = self.meta_connection_id
        welcome_spec = {
            'type': 'VISUAL_EDITOR',
            'version': 2,
            'landing_screen_type': 'welcome_message',
            'media_type': 'text',
            'text_format': {
                'customer_action_type': 'autofill_message',
                'message': {
                    'text': self.welcome_message,
                    'autofill_message': {'content': self.welcome_message},
                },
            },
        }
        link_data = {
            'name': self.headline,
            'message': self.primary_text,
            'description': self.description or '',
            'image_hash': self.external_image_hash,
            'link': 'https://api.whatsapp.com/send',
            # The Marketing API defines this nested value as a JSON string,
            # even though object_story_spec itself is sent as JSON.
            'page_welcome_message': json.dumps(welcome_spec, separators=(',', ':')),
            'call_to_action': {
                'type': 'WHATSAPP_MESSAGE',
                'value': {'app_destination': 'WHATSAPP'},
            },
        }
        story = {'page_id': connection.page_id, 'link_data': link_data}
        if connection.instagram_user_id:
            story['instagram_user_id'] = connection.instagram_user_id
        return {'name': self._meta_name('Creativo'), 'object_story_spec': story}

    def _ad_payload(self):
        return {
            'name': self._meta_name('Anuncio'),
            'adset_id': self.external_adset_id,
            'creative': {'creative_id': self.external_creative_id},
            'status': 'PAUSED',
        }

    @staticmethod
    def _remote_relation_id(value):
        if isinstance(value, dict):
            value = value.get('id')
        return str(value or '')

    def _validate_recovered_step(self, step, record):
        """Fail closed before adopting an object recovered by deterministic name."""
        self.ensure_one()
        if not isinstance(record, dict) or not record.get('id'):
            raise MetaAdsError('La coincidencia de Meta no contiene un ID válido.', ambiguous=True)
        expected_name = self._meta_name(self._REMOTE_STEP_SPECS[step][2])
        if record.get('name') != expected_name:
            raise MetaAdsError('La coincidencia de Meta no conserva el nombre idempotente.', ambiguous=True)
        if step in ('campaign', 'adset', 'ad'):
            status = str(record.get('configured_status') or '').upper()
            if status != 'PAUSED':
                raise MetaAdsError(
                    'El objeto recuperado para %s no está pausado (estado %s).'
                    % (step, status or '?'),
                    ambiguous=True,
                )
        if step == 'campaign' and record.get('objective') != self.campaign_objective:
            raise MetaAdsError('La campaña recuperada tiene otro objetivo.', ambiguous=True)
        if step == 'adset':
            if self._remote_relation_id(record.get('campaign_id')) != self.external_campaign_id:
                raise MetaAdsError('El conjunto recuperado pertenece a otra campaña.', ambiguous=True)
            if record.get('destination_type') != self.destination_type:
                raise MetaAdsError('El conjunto recuperado tiene otro destino.', ambiguous=True)
        if step == 'ad':
            if self._remote_relation_id(record.get('campaign_id')) != self.external_campaign_id:
                raise MetaAdsError('El anuncio recuperado pertenece a otra campaña.', ambiguous=True)
            if self._remote_relation_id(record.get('adset_id')) != self.external_adset_id:
                raise MetaAdsError('El anuncio recuperado pertenece a otro conjunto.', ambiguous=True)
            creative_id = self._remote_relation_id(record.get('creative'))
            if creative_id and creative_id != self.external_creative_id:
                raise MetaAdsError('El anuncio recuperado usa otro creativo.', ambiguous=True)
        return str(record['id'])

    def _start_operation(self, step, state='running'):
        return self.env['creative.meta.operation'].sudo().create({
            'publication_id': self.id,
            'step': step,
            'state': state,
        })

    @staticmethod
    def _finish_operation(operation, *, external_id=False, error=False):
        values = {'finished_at': fields.Datetime.now()}
        if error:
            values.update({
                'state': 'needs_reconcile' if error.ambiguous else 'failed',
                'error_code': error.code,
                'error_subcode': error.subcode,
                'error_type': error.error_type,
                'fbtrace_id': error.fbtrace_id,
                'error_message': str(error)[:1000],
            })
        else:
            values.update({'state': 'succeeded', 'external_id': external_id})
        operation.sudo().write(values)

    def _publish_failure(self, operation, error):
        self._finish_operation(operation, error=error)
        self._system_write({
            'status': 'error',
            'publish_error': str(error)[:1000],
            'reconcile_required': bool(error.ambiguous),
            'reconcile_mode': 'publish' if error.ambiguous else False,
        })
        label = dict(operation._fields['step'].selection).get(operation.step, operation.step)
        self.message_post(body=_('Meta no confirmó el paso “%s”: %s') % (label, str(error)))

    def _create_remote_step(self, step, target_field, callback, client):
        if self[target_field]:
            return True
        operation = self._start_operation(step)
        self._system_write({'publish_step': step, 'publish_error': False})
        try:
            external_id = False
            if step != 'image':
                edge, _field_name, suffix = self._REMOTE_STEP_SPECS[step]
                matches = client.find_named(
                    self.meta_connection_id.ad_account_id,
                    edge,
                    self._meta_name(suffix),
                )
                if len(matches) > 1:
                    raise MetaAdsError(
                        'Existen varias coincidencias para el paso %s; revisalas en Ads Manager.' % step,
                        ambiguous=True,
                    )
                if matches:
                    external_id = self._validate_recovered_step(step, matches[0])
                    self.message_post(body=_(
                        'Se recuperó de forma idempotente el objeto Meta %s (%s).'
                    ) % (step, external_id))
            if not external_id:
                result = callback()
                external_id = (
                    result if isinstance(result, str)
                    else result.get('id') if isinstance(result, dict)
                    else False
                )
            if not external_id:
                raise MetaAdsError(
                    'Meta no devolvió un identificador para el paso %s.' % step,
                    ambiguous=step != 'image',
                )
            self._system_write({target_field: external_id})
            self._finish_operation(operation, external_id=external_id)
            return True
        except MetaAdsError as error:
            self._publish_failure(operation, error)
            return False

    @staticmethod
    def _notification(title, message, level='info', sticky=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': level,
                'sticky': sticky,
            },
        }

    def action_prepare(self):
        self._check_publisher_access()
        for publication in self:
            if publication.status != 'draft':
                raise ValidationError(_('Solo una publicación borrador se puede preparar.'))
            publication._validate_for_meta()
            values = {
                'status': 'prepared',
                'meta_account_id': publication.meta_connection_id.ad_account_id,
                'publish_error': False,
            }
            if not publication.idempotency_key:
                values['idempotency_key'] = uuid.uuid4().hex
            publication._system_write(values)

    def action_publish_paused(self):
        self._check_publisher_access()
        self.ensure_one()
        completed = 0
        for publication in self:
            publication.env.cr.execute(
                'SELECT id FROM creative_publication WHERE id = %s FOR UPDATE',
                [publication.id],
            )
            publication.invalidate_recordset()
            if publication.status not in ('prepared', 'error'):
                raise ValidationError(_('La publicación debe estar preparada.'))
            if publication.reconcile_required:
                raise ValidationError(_(
                    'Hay una escritura de resultado incierto. Sincronizá o conciliá en Meta antes de reintentar.'
                ))
            targeting, phone = publication._validate_for_meta()
            connection = publication.meta_connection_id
            if not connection.publish_enabled:
                raise ValidationError(_('Habilitá “Permitir crear en pausa” en la conexión Meta.'))
            client = connection._get_client()
            raw = base64.b64decode(publication.export_id.file or b'')
            steps = (
                ('image', 'external_image_hash', lambda: client.upload_image(
                    connection.ad_account_id, raw, publication.export_id.filename,
                )),
                ('campaign', 'external_campaign_id', lambda: client.create_campaign(
                    connection.ad_account_id, publication._campaign_payload(),
                )),
                ('adset', 'external_adset_id', lambda: client.create_adset(
                    connection.ad_account_id, publication._adset_payload(targeting, phone),
                )),
                ('creative', 'external_creative_id', lambda: client.create_creative(
                    connection.ad_account_id, publication._creative_payload(),
                )),
                ('ad', 'external_ad_id', lambda: client.create_ad(
                    connection.ad_account_id, publication._ad_payload(),
                )),
            )
            if not all(
                publication._create_remote_step(step, field_name, callback, client)
                for step, field_name, callback in steps
            ):
                continue
            publication._system_write({
                'status': 'paused',
                'publish_step': 'done',
                'publish_error': False,
                'last_publish_at': fields.Datetime.now(),
                'remote_configured_status': 'PAUSED',
                'remote_effective_status': 'PAUSED',
                'reconcile_required': False,
                'reconcile_mode': False,
            })
            publication.message_post(body=_(
                'Recursos creados en Meta en estado PAUSED. Ad ID: %s'
            ) % publication.external_ad_id)
            completed += 1
        return self._notification(
            _('Publicación Meta'),
            _('%s publicación(es) creadas en pausa.') % completed,
            'success' if completed == len(self) else 'warning',
            completed != len(self),
        )

    def action_reconcile_meta(self):
        self._check_publisher_access()
        reconciled = 0
        for publication in self:
            if not publication.reconcile_required:
                continue
            operation = publication._start_operation('reconcile')
            try:
                if publication.reconcile_mode == 'delivery' or publication.publish_step == 'done':
                    client = publication.meta_connection_id._get_client()
                    remote_campaign = client.get_delivery_object(publication.external_campaign_id)
                    remote_adset = client.get_delivery_object(publication.external_adset_id)
                    remote_ad = client.get_delivery_object(publication.external_ad_id)
                    campaign_status = str(remote_campaign.get('configured_status') or '').upper()
                    adset_status = str(remote_adset.get('configured_status') or '').upper()
                    ad_status = str(remote_ad.get('configured_status') or '').upper()
                    if campaign_status in ('PAUSED', 'ARCHIVED'):
                        local_status = 'archived' if campaign_status == 'ARCHIVED' else 'paused'
                    elif {campaign_status, adset_status, ad_status} == {'ACTIVE'}:
                        local_status = 'active'
                    else:
                        raise MetaAdsError(
                            'La jerarquía tiene estados mixtos (%s / %s / %s). '
                            'Un activador debe ejecutar “Pausar en Meta”.'
                            % (campaign_status or '?', adset_status or '?', ad_status or '?')
                        )
                    publication._system_write({
                        'status': local_status,
                        'remote_configured_status': ad_status,
                        'remote_effective_status': remote_ad.get('effective_status') or ad_status,
                        'reconcile_required': False,
                        'reconcile_mode': False,
                        'sync_error': False,
                    })
                    publication._finish_operation(operation, external_id=publication.external_ad_id)
                    publication.message_post(body=_(
                        'Conciliación de entrega Meta: campaña %s, conjunto %s, anuncio %s.'
                    ) % (campaign_status, adset_status, ad_status))
                    reconciled += 1
                    continue
                if publication.publish_step == 'image':
                    # Ad images are content-addressed. Uploading the exact same
                    # clean file again is safe and cannot start delivery.
                    publication._system_write({
                        'external_image_hash': False,
                        'reconcile_required': False,
                        'reconcile_mode': False,
                        'publish_error': False,
                    })
                    publication._finish_operation(operation)
                    reconciled += 1
                    continue
                edge, target_field, suffix = self._REMOTE_STEP_SPECS.get(
                    publication.publish_step, (False, False, False),
                )
                if not edge:
                    raise MetaAdsError('No se reconoce el paso que necesita conciliación.')
                client = publication.meta_connection_id._get_client()
                matches = client.find_named(
                    publication.meta_connection_id.ad_account_id,
                    edge,
                    publication._meta_name(suffix),
                )
                if len(matches) != 1:
                    raise MetaAdsError(
                        'La conciliación encontró %s coincidencias; se esperaba exactamente una.' % len(matches)
                    )
                external_id = publication._validate_recovered_step(
                    publication.publish_step, matches[0],
                )
                publication._system_write({
                    target_field: external_id,
                    'reconcile_required': False,
                    'reconcile_mode': False,
                    'publish_error': False,
                })
                publication._finish_operation(operation, external_id=external_id)
                publication.message_post(body=_(
                    'Conciliación Meta: se recuperó %s para el paso %s.'
                ) % (external_id, publication.publish_step))
                reconciled += 1
            except MetaAdsError as error:
                publication._finish_operation(operation, error=error)
                publication._system_write({'publish_error': str(error)[:1000]})
        return self._notification(
            _('Conciliación Meta'),
            _('%s de %s publicación(es) conciliadas.') % (reconciled, len(self)),
            'success' if reconciled == len(self) else 'warning',
            reconciled != len(self),
        )

    @staticmethod
    def _number(value, integer=False):
        try:
            number = float(value or 0)
        except (TypeError, ValueError):
            number = 0.0
        return int(round(number)) if integer else number

    @classmethod
    def _conversation_total(cls, actions):
        total = 0.0
        for action in actions or []:
            action_type = str(action.get('action_type') or '').lower()
            if action_type.endswith('messaging_conversation_started_7d'):
                total += cls._number(action.get('value'))
        return total

    def _metric_values(self, row):
        return {
            'spend': self._number(row.get('spend')),
            'impressions': self._number(row.get('impressions'), integer=True),
            'reach': self._number(row.get('reach'), integer=True),
            'clicks': self._number(row.get('clicks'), integer=True),
            'inline_link_clicks': self._number(row.get('inline_link_clicks'), integer=True),
            'meta_conversation_count': self._conversation_total(row.get('actions')),
            'ctr': self._number(row.get('ctr')),
            'cpc': self._number(row.get('cpc')),
            'cpm': self._number(row.get('cpm')),
            'frequency': self._number(row.get('frequency')),
        }

    def _sync_meta_metrics(self):
        self.ensure_one()
        operation = self._start_operation('sync')
        attempt_at = fields.Datetime.now()
        self._system_write({'last_sync_attempt_at': attempt_at})
        try:
            client = self.meta_connection_id._get_client()
            remote = client.get_ad(self.external_ad_id)
            aggregate_rows = client.get_insights(self.external_ad_id, date_preset='maximum')
            aggregate = aggregate_rows[0] if aggregate_rows else {}
            today = fields.Date.context_today(self)
            since = today - timedelta(days=27)
            daily_rows = client.get_insights(
                self.external_ad_id,
                time_range={'since': fields.Date.to_string(since), 'until': fields.Date.to_string(today)},
                time_increment=1,
            )
            metric_model = self.env['creative.meta.metric.day'].sudo()
            for row in daily_rows:
                metric_date = fields.Date.to_date(row.get('date_start'))
                if not metric_date:
                    continue
                parsed = self._metric_values(row)
                values = {
                    'publication_id': self.id,
                    'external_ad_id': self.external_ad_id,
                    'date': metric_date,
                    'spend': parsed['spend'],
                    'impressions': parsed['impressions'],
                    'reach': parsed['reach'],
                    'clicks': parsed['clicks'],
                    'inline_link_clicks': parsed['inline_link_clicks'],
                    'conversations': parsed['meta_conversation_count'],
                    'ctr': parsed['ctr'],
                    'cpc': parsed['cpc'],
                    'cpm': parsed['cpm'],
                    'frequency': parsed['frequency'],
                    'actions_json': row.get('actions') or [],
                    'cost_per_action_json': row.get('cost_per_action_type') or [],
                    'synced_at': attempt_at,
                }
                metric = metric_model.search([
                    ('publication_id', '=', self.id),
                    ('external_ad_id', '=', self.external_ad_id),
                    ('date', '=', metric_date),
                ], limit=1)
                if metric:
                    metric.write(values)
                else:
                    metric_model.create(values)

            values = self._metric_values(aggregate)
            configured = remote.get('configured_status') or ''
            effective = remote.get('effective_status') or ''
            issues = {
                key: remote.get(key)
                for key in ('issues_info', 'ad_review_feedback', 'failed_delivery_checks')
                if remote.get(key)
            }
            values.update({
                'remote_configured_status': configured,
                'remote_effective_status': effective,
                'remote_issues_json': issues,
                'metrics_json': aggregate,
                'last_sync_at': attempt_at,
                'sync_error': False,
            })
            if configured == 'ACTIVE':
                values['status'] = 'active'
            elif configured in ('PAUSED', 'ARCHIVED'):
                values['status'] = 'archived' if configured == 'ARCHIVED' else 'paused'
            self._system_write(values)
            self._finish_operation(operation, external_id=self.external_ad_id)
            return True
        except (MetaAdsError, UserError) as error:
            if not isinstance(error, MetaAdsError):
                error = MetaAdsError(str(error))
            self._finish_operation(operation, error=error)
            self._system_write({
                'sync_error': str(error)[:1000],
                'reconcile_required': self.reconcile_required or bool(error.ambiguous),
            })
            return False

    def action_sync_meta_metrics(self):
        self._check_publisher_access()
        successes = 0
        for publication in self:
            if not publication.external_ad_id:
                raise ValidationError(_('La publicación todavía no tiene Ad ID de Meta.'))
            if not publication.meta_connection_id.metrics_enabled:
                raise ValidationError(_('La sincronización está deshabilitada en la conexión Meta.'))
            successes += int(publication._sync_meta_metrics())
        return self._notification(
            _('Métricas Meta'),
            _('%s de %s publicación(es) sincronizadas.') % (successes, len(self)),
            'success' if successes == len(self) else 'warning',
            successes != len(self),
        )

    @api.model
    def _cron_sync_meta_metrics(self, limit=50):
        publications = self.search([
            ('external_ad_id', '!=', False),
            ('sync_enabled', '=', True),
            ('meta_connection_id.metrics_enabled', '=', True),
            ('status', 'in', ['paused', 'active', 'error']),
        ], limit=limit, order='last_sync_attempt_at asc NULLS FIRST, id')
        for publication in publications:
            with self.env.cr.savepoint():
                publication._sync_meta_metrics()
        return len(publications)

    @classmethod
    def _json_contains(cls, actual, expected):
        """Compare a submitted JSON snapshot with Meta's enriched response."""
        if isinstance(expected, dict):
            return isinstance(actual, dict) and all(
                key in actual and cls._json_contains(actual[key], value)
                for key, value in expected.items()
            )
        if isinstance(expected, list):
            if not isinstance(actual, list):
                return False
            return all(
                any(cls._json_contains(candidate, item) for candidate in actual)
                for item in expected
            )
        return str(actual) == str(expected)

    @staticmethod
    def _remote_timestamp(value):
        if value in (False, None, ''):
            return False
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, datetime):
            moment = value
        else:
            try:
                moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            except ValueError:
                return False
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.timestamp()

    def _validate_remote_for_activation(self, client):
        """Re-read the spend-bearing hierarchy before any ACTIVE write."""
        self.ensure_one()
        campaign = client.get_campaign(self.external_campaign_id)
        adset = client.get_adset(self.external_adset_id)
        ad = client.get_ad(self.external_ad_id)
        objects = (
            ('campaña', campaign, self.external_campaign_id, self._meta_name('Campaña')),
            ('conjunto', adset, self.external_adset_id, self._meta_name('Conjunto')),
            ('anuncio', ad, self.external_ad_id, self._meta_name('Anuncio')),
        )
        for label, remote, expected_id, expected_name in objects:
            if not isinstance(remote, dict) or str(remote.get('id') or '') != expected_id:
                raise MetaAdsError('Meta devolvió un %s distinto del esperado.' % label)
            if remote.get('name') != expected_name:
                raise MetaAdsError('El nombre remoto de %s cambió; se bloqueó la activación.' % label)
            configured = str(remote.get('configured_status') or '').upper()
            if configured not in ('PAUSED', 'ACTIVE'):
                raise MetaAdsError(
                    'El estado remoto de %s no permite activar (%s).' % (label, configured or '?')
                )
        if campaign.get('objective') != self.campaign_objective:
            raise MetaAdsError('El objetivo remoto de la campaña no coincide con Odoo.')
        expected_categories = [] if self.special_ad_category == 'NONE' else [self.special_ad_category]
        remote_categories = [
            item for item in (campaign.get('special_ad_categories') or []) if item != 'NONE'
        ]
        if sorted(remote_categories) != sorted(expected_categories):
            raise MetaAdsError('La categoría especial remota no coincide con Odoo.')
        if self._remote_relation_id(adset.get('campaign_id')) != self.external_campaign_id:
            raise MetaAdsError('El conjunto remoto pertenece a otra campaña.')
        if self._remote_relation_id(ad.get('campaign_id')) != self.external_campaign_id:
            raise MetaAdsError('El anuncio remoto pertenece a otra campaña.')
        if self._remote_relation_id(ad.get('adset_id')) != self.external_adset_id:
            raise MetaAdsError('El anuncio remoto pertenece a otro conjunto.')
        if self._remote_relation_id(ad.get('creative')) != self.external_creative_id:
            raise MetaAdsError('El anuncio remoto usa otro creativo.')
        if adset.get('destination_type') != self.destination_type:
            raise MetaAdsError('El destino remoto dejó de ser WhatsApp.')
        promoted = adset.get('promoted_object') or {}
        if not isinstance(promoted, dict):
            raise MetaAdsError('Meta devolvió un destino promocionado inválido.')
        expected_phone = ''.join(
            character for character in self.meta_connection_id.whatsapp_phone_number or ''
            if character.isdigit()
        )
        remote_phone = ''.join(
            character for character in str(promoted.get('whatsapp_phone_number') or '')
            if character.isdigit()
        )
        if str(promoted.get('page_id') or '') != self.meta_connection_id.page_id:
            raise MetaAdsError('La página remota del conjunto no coincide con la conexión.')
        if remote_phone != expected_phone:
            raise MetaAdsError('El WhatsApp remoto del conjunto no coincide con la conexión.')
        budget_field = 'daily_budget' if self.budget_type == 'daily' else 'lifetime_budget'
        expected_budget = self._minor_units(
            self.daily_budget if self.budget_type == 'daily' else self.lifetime_budget
        )
        try:
            remote_budget = int(float(adset.get(budget_field)))
        except (TypeError, ValueError):
            remote_budget = -1
        if remote_budget != expected_budget:
            raise MetaAdsError('El presupuesto remoto cambió; se bloqueó la activación.')
        expected_end = self._remote_timestamp(self._meta_datetime(self.end_at))
        remote_end = self._remote_timestamp(adset.get('end_time'))
        if not remote_end or abs(remote_end - expected_end) > 60:
            raise MetaAdsError('La fecha final remota cambió; se bloqueó la activación.')
        expected_targeting = self._json_object(self.targeting_json, _('La segmentación'))
        remote_targeting = adset.get('targeting') or {}
        if not self._json_contains(remote_targeting, expected_targeting):
            raise MetaAdsError('La segmentación remota cambió; se bloqueó la activación.')
        return ad

    def _execute_queued_activation(self, operation):
        """Execute a durable activation command selected by the cron worker."""
        self.ensure_one()
        if self.meta_connection_id:
            self.meta_connection_id._lock_credential_state()
        operation.sudo().write({'state': 'running'})
        try:
            if not self.delivery_pending or self.status != 'paused':
                raise ValidationError(_('La publicación ya no está pendiente de activación.'))
            self._validate_for_meta()
            connection = self.meta_connection_id
            if not connection.activation_enabled:
                raise ValidationError(_('La activación está deshabilitada en la conexión Meta.'))
            if not all((self.external_ad_id, self.external_adset_id, self.external_campaign_id)):
                raise ValidationError(_('Faltan IDs remotos para activar la jerarquía.'))
            client = connection._get_client()
        except (UserError, ValidationError) as error:
            safe_error = MetaAdsError(str(error))
            self._finish_operation(operation, error=safe_error)
            self._system_write({
                'delivery_pending': False,
                'sync_error': str(safe_error)[:1000],
            })
            self.message_post(body=_('La activación en cola fue rechazada: %s') % safe_error)
            return False

        try:
            self._validate_remote_for_activation(client)
            client.set_status(self.external_ad_id, 'ACTIVE')
            client.set_status(self.external_adset_id, 'ACTIVE')
            # The spend-bearing parent is deliberately activated last.
            client.set_status(self.external_campaign_id, 'ACTIVE')
            remote = client.get_ad(self.external_ad_id)
            configured = remote.get('configured_status') or 'ACTIVE'
            effective = remote.get('effective_status') or configured
            self._system_write({
                'status': 'active',
                'delivery_pending': False,
                'remote_configured_status': configured,
                'remote_effective_status': effective,
                'sync_error': False,
                'reconcile_required': False,
                'reconcile_mode': False,
            })
            self._finish_operation(operation, external_id=self.external_ad_id)
            self.message_post(body=_(
                'Activación procesada por la cola durable. Estado efectivo inicial: %s'
            ) % effective)
            return True
        except MetaAdsError as error:
            pause_error = False
            try:
                client.set_status(self.external_campaign_id, 'PAUSED')
            except MetaAdsError as nested:
                pause_error = nested
            uncertain = MetaAdsError(
                '%s%s' % (
                    str(error),
                    ' Además, Meta no confirmó la pausa de seguridad: %s' % pause_error
                    if pause_error else '',
                ),
                code=error.code,
                subcode=error.subcode,
                error_type=error.error_type,
                fbtrace_id=error.fbtrace_id,
                transient=error.transient,
                ambiguous=True,
            )
            self._finish_operation(operation, error=uncertain)
            self._system_write({
                'delivery_pending': False,
                'sync_error': str(uncertain)[:1000],
                'reconcile_required': True,
                'reconcile_mode': 'delivery',
            })
            self.message_post(body=_('La activación requiere conciliación: %s') % uncertain)
            return False

    @api.model
    def _cron_process_meta_commands(self, limit=10):
        operations = self.env['creative.meta.operation'].sudo().search([
            ('step', '=', 'activate'),
            ('state', '=', 'queued'),
        ], limit=limit, order='id')
        processed = 0
        for operation in operations:
            with self.env.cr.savepoint():
                publication_id = operation.publication_id.id
                self.env.cr.execute(
                    'SELECT id FROM creative_publication WHERE id = %s FOR UPDATE SKIP LOCKED',
                    [publication_id],
                )
                if not self.env.cr.fetchone():
                    continue
                operation.invalidate_recordset()
                publication = self.sudo().browse(publication_id)
                publication.invalidate_recordset()
                if operation.state != 'queued':
                    continue
                publication._execute_queued_activation(operation)
                processed += 1
        return processed

    def action_activate(self):
        self._check_activator_access()
        self.ensure_one()
        self.env.cr.execute(
            'SELECT id FROM creative_publication WHERE id = %s FOR UPDATE', [self.id],
        )
        self.invalidate_recordset()
        if self.meta_connection_id:
            self.meta_connection_id._lock_credential_state()
        if self.status != 'paused':
            raise ValidationError(_('Solo se puede activar una publicación pausada.'))
        if self.reconcile_required:
            raise ValidationError(_('Conciliá el estado remoto antes de volver a activar.'))
        if self.delivery_pending:
            raise ValidationError(_('Ya existe una activación en cola.'))
        self._validate_for_meta()
        connection = self.meta_connection_id
        if not connection.activation_enabled:
            raise ValidationError(_('La activación está deshabilitada en la conexión Meta.'))
        if not all((self.external_ad_id, self.external_adset_id, self.external_campaign_id)):
            raise ValidationError(_('Faltan IDs remotos para activar la jerarquía.'))
        self._start_operation('activate', state='queued')
        self._system_write({'delivery_pending': True, 'sync_error': False})
        self.message_post(body=_(
            'Activación en cola durable. La campaña seguirá pausada hasta que el worker valide la jerarquía.'
        ))
        cron = self.env.ref('creative_lab.cron_process_creative_meta_commands', raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()
        return self._notification(
            _('Activación Meta'),
            _('La activación quedó en cola y será procesada luego de validar la configuración remota.'),
            'info',
        )

    def action_pause(self):
        self._check_activator_access()
        self.ensure_one()
        paused = 0
        for publication in self:
            publication.env.cr.execute(
                'SELECT id FROM creative_publication WHERE id = %s FOR UPDATE', [publication.id],
            )
            publication.invalidate_recordset()
            if publication.status != 'active' and not (
                publication.reconcile_required and publication.reconcile_mode == 'delivery'
            ) and not publication.delivery_pending and publication.remote_configured_status != 'ACTIVE':
                raise ValidationError(_(
                    'Solo se puede pausar una publicación activa o con estado remoto incierto.'
                ))
            if not publication.external_campaign_id:
                raise ValidationError(_('La publicación no tiene una campaña remota.'))
            queued = self.env['creative.meta.operation'].sudo().search([
                ('publication_id', '=', publication.id),
                ('step', '=', 'activate'),
                ('state', '=', 'queued'),
            ])
            for command in queued:
                publication._finish_operation(
                    command,
                    error=MetaAdsError('Activación cancelada por una orden de pausa.'),
                )
            if publication.delivery_pending:
                publication._system_write({'delivery_pending': False})
            operation = publication._start_operation('pause')
            client = publication.meta_connection_id._get_client()
            try:
                # Pausing the parent first stops delivery before touching children.
                client.set_status(publication.external_campaign_id, 'PAUSED')
                if publication.external_adset_id:
                    client.set_status(publication.external_adset_id, 'PAUSED')
                if publication.external_ad_id:
                    client.set_status(publication.external_ad_id, 'PAUSED')
                publication._system_write({
                    'status': 'paused',
                    'delivery_pending': False,
                    'remote_configured_status': 'PAUSED',
                    'remote_effective_status': 'PAUSED',
                    'sync_error': False,
                    'reconcile_required': False,
                    'reconcile_mode': False,
                })
                publication._finish_operation(operation, external_id=publication.external_campaign_id)
                publication.message_post(body=_('Jerarquía pausada en Meta.'))
                paused += 1
            except MetaAdsError as error:
                publication._finish_operation(operation, error=error)
                publication._system_write({
                    'sync_error': str(error)[:1000],
                    'delivery_pending': False,
                    'reconcile_required': True,
                    'reconcile_mode': 'delivery',
                })
        return self._notification(
            _('Pausa Meta'),
            _('%s de %s publicación(es) pausadas.') % (paused, len(self)),
            'success' if paused == len(self) else 'warning',
            paused != len(self),
        )

    def action_archive(self):
        self._check_publisher_access()
        for publication in self:
            if publication.delivery_pending:
                raise ValidationError(_('Cancelá o procesá la activación en cola antes de archivar.'))
            if publication.status == 'active' or publication.remote_configured_status == 'ACTIVE':
                raise ValidationError(_('Pausá la campaña en Meta antes de archivarla.'))
            if publication.reconcile_required:
                raise ValidationError(_('Conciliá el estado remoto antes de archivar.'))
            publication._system_write({'status': 'archived'})


class CreativeOutcome(models.Model):
    _name = 'creative.outcome'
    _description = 'Resultado atribuible a un creativo'
    _inherit = ['mail.thread']
    _order = 'occurred_at desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='Resultado', required=True)
    publication_id = fields.Many2one(
        'creative.publication',
        string='Publicación',
        required=True,
        check_company=True,
        ondelete='cascade',
        index=True,
    )
    creative_id = fields.Many2one(related='publication_id.creative_id', store=True, readonly=True)
    version_id = fields.Many2one(related='publication_id.version_id', store=True, readonly=True)
    company_id = fields.Many2one(
        related='publication_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    event_type = fields.Selection(
        [
            ('conversation', 'Conversación iniciada'),
            ('qualified', 'Conversación calificada'),
            ('meeting_booked', 'Reunión agendada'),
            ('meeting_held', 'Reunión realizada'),
            ('opportunity', 'Oportunidad creada'),
            ('sale', 'Venta'),
        ],
        required=True,
        index=True,
    )
    occurred_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    partner_id = fields.Many2one('res.partner', string='Contacto', ondelete='set null')
    lead_id = fields.Many2one('crm.lead', string='Lead/oportunidad', check_company=True, ondelete='set null')
    whatsapp_message_id = fields.Char(string='WhatsApp Message ID', index=True)
    referral_ad_id = fields.Char(string='Ad ID de referencia', index=True)
    amount = fields.Monetary(string='Importe')
    source = fields.Selection(
        [('manual', 'Manual'), ('whatsapp', 'WhatsApp'), ('crm', 'CRM'), ('ai', 'Clasificado por IA')],
        default='manual',
        required=True,
    )
    confidence = fields.Float(string='Confianza', default=1.0)
    evidence = fields.Text(string='Evidencia')
    confirmed = fields.Boolean(
        string='Confirmado por una persona/sistema',
        default=True,
        tracking=True,
    )

    _valid_confidence = models.Constraint(
        'CHECK(confidence >= 0 AND confidence <= 1)',
        'La confianza debe estar entre 0 y 1.',
    )

    @api.constrains('lead_id', 'company_id')
    def _check_lead_company(self):
        for outcome in self:
            if outcome.lead_id.company_id and outcome.lead_id.company_id != outcome.company_id:
                raise ValidationError(_('El lead y el resultado deben pertenecer a la misma compañía.'))
