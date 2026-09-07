# -*- coding: utf-8 -*-

import os
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from ..services.meta_ads import MetaAdsClient, MetaAdsError


class CreativeMetaAccount(models.Model):
    _name = 'creative.meta.account'
    _description = 'Conexión de Creative Lab con Meta Ads'
    _inherit = ['mail.thread']
    _order = 'company_id, name'
    _check_company_auto = True

    _RESULT_FIELDS = {
        'currency_id', 'timezone_name', 'remote_name', 'remote_account_status',
        'connection_state', 'last_test_at', 'last_error',
    }

    _unique_account_company = models.Constraint(
        'UNIQUE(company_id, ad_account_id)',
        'La cuenta publicitaria ya está configurada para esta compañía.',
    )

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, default=lambda self: self.env.company,
        index=True, ondelete='cascade',
    )
    api_version = fields.Char(string='Versión Graph API', default='v26.0', required=True)
    token_env_var = fields.Char(
        string='Variable del token', default='CREATIVE_LAB_META_ACCESS_TOKEN', required=True,
        help='Nombre de la variable de entorno del contenedor. El token no se guarda en Odoo.',
    )
    app_secret_env_var = fields.Char(
        string='Variable del App Secret',
        help='Opcional. Si existe, se envía appsecret_proof en cada llamada.',
    )
    token_available = fields.Boolean(string='Token disponible', compute='_compute_token_available')
    ad_account_id = fields.Char(string='Ad Account ID', required=True, tracking=True)
    page_id = fields.Char(string='Facebook Page ID', required=True, tracking=True)
    instagram_user_id = fields.Char(string='Instagram User ID')
    whatsapp_phone_number = fields.Char(
        string='WhatsApp destino', required=True,
        help='Número internacional vinculado a la página, con código de país.',
    )
    currency_id = fields.Many2one('res.currency', string='Moneda de Meta', readonly=True)
    timezone_name = fields.Char(string='Zona horaria de Meta', readonly=True)
    remote_name = fields.Char(string='Nombre en Meta', readonly=True)
    remote_account_status = fields.Char(string='Estado de cuenta', readonly=True)
    connection_state = fields.Selection(
        [('untested', 'Sin probar'), ('ready', 'Lista'), ('error', 'Error')],
        default='untested', required=True, readonly=True, tracking=True,
    )
    last_test_at = fields.Datetime(string='Última prueba', readonly=True)
    last_error = fields.Text(string='Último error', readonly=True)

    metrics_enabled = fields.Boolean(string='Sincronizar métricas', default=True)
    publish_enabled = fields.Boolean(
        string='Permitir crear en pausa', default=False,
        help='Permite crear recursos reales en Meta. Siempre se crean pausados.',
    )
    activation_enabled = fields.Boolean(
        string='Permitir activación', default=False,
        help='Habilita la acción separada que puede comenzar a gastar.',
    )
    max_daily_budget = fields.Monetary(
        string='Tope diario por conjunto', currency_field='currency_id', default=0.0,
    )
    max_lifetime_budget = fields.Monetary(
        string='Tope total por conjunto', currency_field='currency_id', default=0.0,
    )
    max_campaign_days = fields.Integer(string='Duración máxima', default=30)

    @api.depends('token_env_var')
    def _compute_token_available(self):
        for account in self:
            token = os.environ.get(account.token_env_var or '')
            account.token_available = bool(token and token.strip())

    @api.constrains('api_version')
    def _check_api_version(self):
        for account in self:
            if not re.fullmatch(r'v\d+\.\d+', account.api_version or ''):
                raise ValidationError(_('Usá una versión Graph API explícita, por ejemplo v26.0.'))

    @api.constrains('ad_account_id', 'page_id', 'instagram_user_id')
    def _check_meta_ids(self):
        for account in self:
            values = (account.ad_account_id, account.page_id, account.instagram_user_id)
            if any(value and not str(value).isdigit() for value in values):
                raise ValidationError(_('Los IDs de cuenta, página e Instagram deben ser numéricos.'))

    @api.constrains('whatsapp_phone_number')
    def _check_phone(self):
        for account in self:
            digits = (account.whatsapp_phone_number or '').lstrip('+')
            if not (8 <= len(digits) <= 15 and digits.isdigit()):
                raise ValidationError(_('El WhatsApp debe ser un número internacional válido de 8 a 15 dígitos.'))

    @api.constrains('token_env_var', 'app_secret_env_var')
    def _check_env_names(self):
        pattern = re.compile(r'^[A-Z][A-Z0-9_]*$')
        for account in self:
            for value in filter(None, (account.token_env_var, account.app_secret_env_var)):
                if not pattern.fullmatch(value):
                    raise ValidationError(_('Los nombres de variables deben usar MAYÚSCULAS, números y guiones bajos.'))

    @api.constrains('max_daily_budget', 'max_lifetime_budget', 'max_campaign_days')
    def _check_caps(self):
        for account in self:
            if account.max_daily_budget < 0 or account.max_lifetime_budget < 0:
                raise ValidationError(_('Los topes de presupuesto no pueden ser negativos.'))
            if account.max_campaign_days < 1:
                raise ValidationError(_('La duración máxima debe ser al menos un día.'))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_admin_access()
        cleaned = []
        for incoming in vals_list:
            vals = dict(incoming)
            if self._RESULT_FIELDS.intersection(vals):
                raise AccessError(_('Los resultados de conexión solo los actualiza el sistema.'))
            vals['ad_account_id'] = self._clean_id(vals.get('ad_account_id'))
            if 'page_id' in vals:
                vals['page_id'] = str(vals.get('page_id') or '').strip()
            if 'instagram_user_id' in vals:
                vals['instagram_user_id'] = str(vals.get('instagram_user_id') or '').strip()
            vals['whatsapp_phone_number'] = self._clean_phone(vals.get('whatsapp_phone_number'))
            cleaned.append(vals)
        return super().create(cleaned)

    def write(self, vals):
        self._check_admin_access()
        vals = dict(vals)
        if 'ad_account_id' in vals:
            vals['ad_account_id'] = self._clean_id(vals['ad_account_id'])
        if 'page_id' in vals:
            vals['page_id'] = str(vals.get('page_id') or '').strip()
        if 'instagram_user_id' in vals:
            vals['instagram_user_id'] = str(vals.get('instagram_user_id') or '').strip()
        if 'whatsapp_phone_number' in vals:
            vals['whatsapp_phone_number'] = self._clean_phone(vals['whatsapp_phone_number'])
        if self._RESULT_FIELDS.intersection(vals):
            raise AccessError(_('Los resultados de conexión solo los actualiza el sistema.'))
        identity = {
            'company_id', 'ad_account_id', 'page_id', 'instagram_user_id',
            'whatsapp_phone_number', 'api_version',
        }
        if identity.intersection(vals):
            used = self.env['creative.publication'].sudo().search_count([
                ('meta_connection_id', 'in', self.ids),
                ('status', '!=', 'draft'),
            ])
            if used:
                raise ValidationError(_('La identidad de una conexión usada no se puede cambiar; creá otra conexión.'))
        must_retest = bool((identity | {'token_env_var', 'app_secret_env_var'}).intersection(vals))
        result = super().write(vals)
        if must_retest:
            self._system_write({
                'currency_id': False,
                'timezone_name': False,
                'remote_name': False,
                'remote_account_status': False,
                'connection_state': 'untested',
                'last_test_at': False,
                'last_error': False,
            })
        return result

    @staticmethod
    def _clean_id(value):
        clean = str(value or '').strip()
        return clean[4:] if clean.startswith('act_') else clean

    @staticmethod
    def _clean_phone(value):
        digits = ''.join(character for character in str(value or '') if character.isdigit())
        return '+%s' % digits if digits else ''

    def _check_admin_access(self):
        if not self.env.user.has_group('creative_lab.grupo_creative_administrador'):
            raise AccessError(_('Solo un administrador de Creative Lab configura conexiones de Meta.'))

    def _system_write(self, vals):
        return super(CreativeMetaAccount, self).write(vals)

    def _get_client(self):
        self.ensure_one()
        token = (os.environ.get(self.token_env_var or '') or '').strip()
        if not token:
            raise UserError(_(
                'No existe la variable %s dentro del contenedor de Odoo.'
            ) % (self.token_env_var or '(sin nombre)'))
        app_secret = (
            (os.environ.get(self.app_secret_env_var or '') or '').strip()
            if self.app_secret_env_var else False
        )
        return MetaAdsClient(token, self.api_version, app_secret=app_secret)

    def action_test_connection(self):
        self.ensure_one()
        self._check_admin_access()
        now = fields.Datetime.now()
        try:
            client = self._get_client()
            account = client.get_account(self.ad_account_id)
            page = client.get_page(self.page_id)
            if str(account.get('account_status') or '') != '1':
                raise ValidationError(_(
                    'La cuenta publicitaria no está activa (estado %s, motivo %s).'
                ) % (account.get('account_status') or '?', account.get('disable_reason') or '-'))
            currency = self.env['res.currency'].with_context(active_test=False).search(
                [('name', '=', account.get('currency'))], limit=1,
            )
            if not currency:
                raise ValidationError(_(
                    'Meta usa la moneda %s, que no existe en Odoo.'
                ) % (account.get('currency') or '?'))
            self._system_write({
                'currency_id': currency.id,
                'timezone_name': account.get('timezone_name'),
                'remote_name': account.get('name'),
                'remote_account_status': str(account.get('account_status') or ''),
                'connection_state': 'ready',
                'last_test_at': now,
                'last_error': False,
            })
            message = _('Conexión lista: %s · Página %s') % (
                account.get('name') or account.get('id'), page.get('name') or page.get('id'),
            )
            level = 'success'
        except (MetaAdsError, UserError, ValidationError) as error:
            message = str(error)[:1000]
            self._system_write({
                'connection_state': 'error',
                'last_test_at': now,
                'last_error': message,
            })
            level = 'danger'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _('Meta Ads'), 'message': message, 'type': level, 'sticky': level == 'danger'},
        }


class CreativeMetaMetricDay(models.Model):
    _name = 'creative.meta.metric.day'
    _description = 'Métrica diaria de Meta Ads'
    _order = 'date desc, id desc'
    _check_company_auto = True

    _unique_publication_date = models.Constraint(
        'UNIQUE(publication_id, external_ad_id, date)',
        'Ya existe una métrica para este anuncio y fecha.',
    )

    publication_id = fields.Many2one(
        'creative.publication', required=True, index=True, ondelete='cascade', check_company=True,
    )
    company_id = fields.Many2one(related='publication_id.company_id', store=True, readonly=True, index=True)
    currency_id = fields.Many2one(related='publication_id.ad_currency_id', store=True, readonly=True)
    external_ad_id = fields.Char(required=True, index=True, readonly=True)
    date = fields.Date(required=True, index=True, readonly=True)
    spend = fields.Monetary(currency_field='currency_id', readonly=True)
    impressions = fields.Integer(readonly=True)
    reach = fields.Integer(readonly=True)
    clicks = fields.Integer(readonly=True)
    inline_link_clicks = fields.Integer(readonly=True)
    conversations = fields.Float(readonly=True)
    ctr = fields.Float(readonly=True)
    cpc = fields.Monetary(currency_field='currency_id', readonly=True)
    cpm = fields.Monetary(currency_field='currency_id', readonly=True)
    frequency = fields.Float(readonly=True)
    actions_json = fields.Json(readonly=True)
    cost_per_action_json = fields.Json(readonly=True)
    synced_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)


class CreativeMetaOperation(models.Model):
    _name = 'creative.meta.operation'
    _description = 'Operación auditable de Meta Ads'
    _order = 'id desc'
    _check_company_auto = True

    publication_id = fields.Many2one(
        'creative.publication', required=True, index=True, ondelete='cascade', check_company=True,
    )
    company_id = fields.Many2one(related='publication_id.company_id', store=True, readonly=True, index=True)
    step = fields.Selection([
        ('image', 'Subir imagen'), ('campaign', 'Crear campaña'), ('adset', 'Crear conjunto'),
        ('creative', 'Crear creativo'), ('ad', 'Crear anuncio'), ('activate', 'Activar'),
        ('pause', 'Pausar'), ('sync', 'Sincronizar'), ('reconcile', 'Conciliar'),
    ], required=True, readonly=True)
    state = fields.Selection([
        ('queued', 'En cola'), ('running', 'En curso'),
        ('succeeded', 'Correcta'), ('failed', 'Fallida'),
        ('needs_reconcile', 'Requiere conciliación'),
    ], required=True, default='running', readonly=True, index=True)
    started_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    finished_at = fields.Datetime(readonly=True)
    external_id = fields.Char(readonly=True)
    error_code = fields.Char(readonly=True)
    error_subcode = fields.Char(readonly=True)
    error_type = fields.Char(readonly=True)
    fbtrace_id = fields.Char(readonly=True)
    error_message = fields.Text(readonly=True)
