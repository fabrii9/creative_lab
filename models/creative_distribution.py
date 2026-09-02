# -*- coding: utf-8 -*-

import base64
import hashlib

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


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
            prepared.append(vals)
        return super().create(prepared)

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
    company_id = fields.Many2one(
        related='creative_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
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
    meta_account_id = fields.Char(string='Ad Account ID')
    external_campaign_id = fields.Char(string='Campaign ID', index=True)
    external_adset_id = fields.Char(string='Ad Set ID', index=True)
    external_ad_id = fields.Char(string='Ad ID', index=True)
    external_creative_id = fields.Char(string='Ad Creative ID', index=True)
    destination_phone = fields.Char(string='WhatsApp destino')
    daily_budget = fields.Monetary(string='Presupuesto diario')
    start_at = fields.Datetime(string='Inicio')
    end_at = fields.Datetime(string='Fin')
    last_sync_at = fields.Datetime(string='Última sincronización', readonly=True)
    sync_error = fields.Text(string='Error de sincronización', readonly=True)

    spend = fields.Monetary(string='Gasto', default=0.0)
    impressions = fields.Integer(default=0)
    reach = fields.Integer(default=0)
    clicks = fields.Integer(default=0)
    outcome_ids = fields.One2many('creative.outcome', 'publication_id', string='Resultados')
    conversation_count = fields.Integer(compute='_compute_outcomes', store=True)
    qualified_count = fields.Integer(compute='_compute_outcomes', store=True)
    meeting_count = fields.Integer(compute='_compute_outcomes', store=True)
    sale_count = fields.Integer(compute='_compute_outcomes', store=True)
    attributed_revenue = fields.Monetary(compute='_compute_outcomes', store=True)
    cost_per_conversation = fields.Monetary(compute='_compute_unit_costs')
    cost_per_qualified = fields.Monetary(compute='_compute_unit_costs')
    cost_per_sale = fields.Monetary(compute='_compute_unit_costs')

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('allow_publication_workflow'):
            for vals in vals_list:
                if vals.get('status', 'draft') != 'draft':
                    raise AccessError(_('Las publicaciones deben iniciar como borrador.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'status' in vals and not self.env.context.get('allow_publication_workflow'):
            raise AccessError(_('Usá las acciones de publicación para cambiar el estado.'))
        return super().write(vals)

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

    @api.constrains('creative_id', 'version_id')
    def _check_version(self):
        for publication in self:
            if publication.version_id.creative_id != publication.creative_id:
                raise ValidationError(_('La versión publicada debe pertenecer al creativo.'))

    def _check_publisher_access(self):
        if not self.env.user.has_group('creative_lab.grupo_creative_aprobador'):
            raise AccessError(_('Solo un aprobador/publicador puede cambiar el estado publicitario.'))

    def action_prepare(self):
        self._check_publisher_access()
        for publication in self:
            if publication.version_id.state != 'approved':
                raise ValidationError(_('La versión debe estar aprobada antes de preparar una publicación.'))
            publication.with_context(allow_publication_workflow=True).write({'status': 'prepared'})

    def action_pause(self):
        self._check_publisher_access()
        self.with_context(allow_publication_workflow=True).write({'status': 'paused'})

    def action_activate(self):
        self._check_publisher_access()
        for publication in self:
            if publication.version_id.state != 'approved':
                raise ValidationError(_('La versión debe estar aprobada.'))
            if not publication.external_ad_id:
                raise ValidationError(_('Registrá el Ad ID de Meta antes de marcar la publicación como activa.'))
            publication.with_context(allow_publication_workflow=True).write({'status': 'active'})

    def action_archive(self):
        self._check_publisher_access()
        self.with_context(allow_publication_workflow=True).write({'status': 'archived'})


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
