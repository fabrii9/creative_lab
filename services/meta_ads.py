# -*- coding: utf-8 -*-

"""Small, dependency-free client for the Meta Marketing API.

The access token is sent only in the Authorization header.  Exceptions expose
the structured Meta error fields but never request payloads or credentials.
"""

import base64
import hashlib
import hmac
import json
import re

import requests


class MetaAdsError(Exception):
    """A sanitized error returned by Meta or the HTTP transport."""

    def __init__(
        self,
        message,
        *,
        code=False,
        subcode=False,
        error_type=False,
        fbtrace_id=False,
        transient=False,
        ambiguous=False,
    ):
        super().__init__(message)
        self.message = message
        self.code = str(code) if code not in (False, None, '') else False
        self.subcode = str(subcode) if subcode not in (False, None, '') else False
        self.error_type = error_type or False
        self.fbtrace_id = fbtrace_id or False
        self.transient = bool(transient)
        self.ambiguous = bool(ambiguous)

    def __str__(self):
        details = []
        if self.code:
            details.append('code=%s' % self.code)
        if self.subcode:
            details.append('subcode=%s' % self.subcode)
        if self.fbtrace_id:
            details.append('trace=%s' % self.fbtrace_id)
        suffix = ' (%s)' % ', '.join(details) if details else ''
        return '%s%s' % (self.message, suffix)


class MetaAdsClient:
    """Narrow client used by Creative Lab's publication workflow."""

    API_ROOT = 'https://graph.facebook.com'

    def __init__(self, access_token, api_version='v26.0', app_secret=False, timeout=(10, 60)):
        self.access_token = access_token
        self.api_version = api_version
        self.app_secret = app_secret or False
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': 'Bearer %s' % access_token,
            'User-Agent': 'Odoo-Creative-Lab/19.0',
        })
        self.last_usage_headers = {}

    @property
    def base_url(self):
        return '%s/%s' % (self.API_ROOT, self.api_version)

    def _appsecret_proof(self):
        if not self.app_secret:
            return False
        return hmac.new(
            self.app_secret.encode('utf-8'),
            self.access_token.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _encode(values):
        encoded = {}
        for key, value in (values or {}).items():
            if value is None:
                continue
            if isinstance(value, bool):
                # Meta requires explicit booleans as true/false strings; a bare
                # False must not be dropped from the form body.
                encoded[key] = 'true' if value else 'false'
            elif isinstance(value, (dict, list, tuple)):
                encoded[key] = json.dumps(value, separators=(',', ':'))
            else:
                encoded[key] = value
        return encoded

    def _redact(self, value):
        text = str(value or '')
        secrets = [self.access_token, self.app_secret, self._appsecret_proof()]
        for secret in filter(None, secrets):
            text = text.replace(secret, '[REDACTED]')
        text = re.sub(r'(?i)(access_token|appsecret_proof)=([^&\s]+)', r'\1=[REDACTED]', text)
        return text[:1000]

    def _raise_api_error(self, payload, fallback, *, ambiguous=False):
        error = payload.get('error', {}) if isinstance(payload, dict) else {}
        message = self._redact(error.get('error_user_msg') or error.get('message') or fallback)
        raise MetaAdsError(
            message,
            code=error.get('code'),
            subcode=error.get('error_subcode'),
            error_type=error.get('type'),
            fbtrace_id=error.get('fbtrace_id'),
            transient=error.get('is_transient'),
            ambiguous=ambiguous,
        )

    def _request(self, method, path, *, params=None, data=None):
        method = method.upper()
        url = '%s/%s' % (self.base_url, str(path).lstrip('/'))
        query = self._encode(params)
        body = self._encode(data)
        proof = self._appsecret_proof()
        if proof:
            (query if method == 'GET' else body)['appsecret_proof'] = proof
        try:
            response = self.session.request(
                method,
                url,
                params=query or None,
                data=body or None,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            # A POST may have reached Meta even when its response was lost.  It
            # must be reconciled, never retried automatically.
            raise MetaAdsError(
                self._redact(error),
                transient=True,
                ambiguous=method == 'POST',
            ) from None

        self.last_usage_headers = {
            key: response.headers.get(key)
            for key in ('x-fb-ads-insights-throttle', 'x-ad-account-usage', 'x-business-use-case-usage')
            if response.headers.get(key)
        }
        try:
            payload = response.json()
        except ValueError:
            raise MetaAdsError(
                'Meta devolvió una respuesta no JSON (HTTP %s).' % response.status_code,
                ambiguous=method == 'POST',
            ) from None
        if response.status_code >= 400 or (isinstance(payload, dict) and payload.get('error')):
            error = payload.get('error', {}) if isinstance(payload, dict) else {}
            self._raise_api_error(
                payload,
                'Error HTTP %s de Meta.' % response.status_code,
                ambiguous=(
                    method == 'POST'
                    and (response.status_code >= 500 or bool(error.get('is_transient')))
                ),
            )
        return payload

    @staticmethod
    def account_path(ad_account_id):
        clean = str(ad_account_id or '').strip()
        if clean.startswith('act_'):
            clean = clean[4:]
        return 'act_%s' % clean

    def get_account(self, ad_account_id):
        return self._request(
            'GET',
            self.account_path(ad_account_id),
            params={
                'fields': (
                    'id,name,account_status,disable_reason,currency,'
                    'timezone_name,spend_cap,user_tasks'
                ),
            },
        )

    def get_permissions(self):
        payload = self._request(
            'GET',
            'me/permissions',
            params={'fields': 'permission,status', 'limit': 200},
        )
        if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
            raise MetaAdsError('Meta devolvió un formato inesperado al consultar permisos.')
        granted = set()
        for item in payload['data']:
            if not isinstance(item, dict):
                continue
            permission = str(item.get('permission') or '').strip().lower()
            status = str(item.get('status') or '').strip().lower()
            if permission and status == 'granted':
                granted.add(permission)
        return granted

    def get_page(self, page_id):
        return self._request('GET', page_id, params={'fields': 'id,name'})

    def upload_image(self, ad_account_id, raw_file, _filename):
        payload = self._request(
            'POST',
            '%s/adimages' % self.account_path(ad_account_id),
            data={'bytes': base64.b64encode(raw_file).decode('ascii')},
        )
        images = payload.get('images') or {}
        records = list(images.values()) if isinstance(images, dict) else images
        image = records[0] if records else {}
        image_hash = image.get('hash') if isinstance(image, dict) else False
        if not image_hash:
            raise MetaAdsError('Meta aceptó la imagen pero no devolvió su hash.')
        return image_hash

    def create_campaign(self, ad_account_id, values):
        return self._request(
            'POST',
            '%s/campaigns' % self.account_path(ad_account_id),
            data=values,
        )

    def create_adset(self, ad_account_id, values):
        return self._request(
            'POST',
            '%s/adsets' % self.account_path(ad_account_id),
            data=values,
        )

    def create_creative(self, ad_account_id, values):
        return self._request(
            'POST',
            '%s/adcreatives' % self.account_path(ad_account_id),
            data=values,
        )

    def create_ad(self, ad_account_id, values):
        return self._request(
            'POST',
            '%s/ads' % self.account_path(ad_account_id),
            data=values,
        )

    def find_named(self, ad_account_id, edge, name):
        field_map = {
            'campaigns': 'id,name,configured_status,objective,special_ad_categories',
            'adsets': 'id,name,campaign_id,configured_status,destination_type',
            'adcreatives': 'id,name',
            'ads': 'id,name,campaign_id,adset_id,configured_status,creative',
        }
        if edge not in field_map:
            raise ValueError('Unsupported Meta edge: %s' % edge)
        # Name/EQUAL filtering is not supported on every edge. Compare exact
        # names locally and exhaust pagination before declaring an object absent.
        params = {'fields': field_map[edge], 'limit': 100}
        matches = {}
        seen_cursors = set()
        while True:
            payload = self._request(
                'GET', '%s/%s' % (self.account_path(ad_account_id), edge),
                params=dict(params),
            )
            if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
                raise MetaAdsError('Meta devolvió una búsqueda con formato inesperado.')
            for record in payload['data']:
                if not isinstance(record, dict) or not record.get('id'):
                    raise MetaAdsError('Meta devolvió un objeto sin identificador en la búsqueda.')
                if record.get('name') == name:
                    matches[record['id']] = record
            paging = payload.get('paging') or {}
            if not paging.get('next'):
                return list(matches.values())
            cursor = (paging.get('cursors') or {}).get('after')
            if not cursor or cursor in seen_cursors:
                raise MetaAdsError('No se pudo completar la paginación de la búsqueda en Meta.')
            seen_cursors.add(cursor)
            params['after'] = cursor

    def get_campaign(self, campaign_id):
        fields = ','.join((
            'id', 'name', 'configured_status', 'effective_status', 'objective',
            'special_ad_categories', 'updated_time',
        ))
        return self._request('GET', campaign_id, params={'fields': fields})

    def get_adset(self, adset_id):
        fields = ','.join((
            'id', 'name', 'campaign_id', 'configured_status', 'effective_status',
            'destination_type', 'promoted_object', 'daily_budget', 'lifetime_budget',
            'start_time', 'end_time', 'targeting', 'updated_time',
        ))
        return self._request('GET', adset_id, params={'fields': fields})

    def set_status(self, object_id, status):
        payload = self._request('POST', object_id, data={'status': status})
        if not isinstance(payload, dict) or payload.get('success') is not True:
            raise MetaAdsError(
                'Meta no confirmó el cambio de estado de %s.' % object_id,
                ambiguous=True,
            )
        return payload

    def get_delivery_object(self, object_id):
        payload = self._request(
            'GET',
            object_id,
            params={'fields': 'id,name,configured_status,effective_status,updated_time'},
        )
        if not isinstance(payload, dict):
            raise MetaAdsError('Meta devolvió un estado de entrega inválido.')
        return payload

    def get_creative(self, creative_id):
        return self._request('GET', creative_id, params={
            'fields': 'id,asset_feed_spec,object_story_spec,contextual_multi_ads',
        })

    def get_ad(self, ad_id):
        fields = ','.join((
            'id', 'name', 'campaign_id', 'adset_id', 'creative', 'configured_status',
            'effective_status', 'issues_info', 'ad_review_feedback',
            'failed_delivery_checks', 'updated_time',
        ))
        return self._request('GET', ad_id, params={'fields': fields})

    def get_insights(self, ad_id, *, time_range=None, date_preset=None, time_increment=None):
        fields = ','.join((
            'account_id', 'campaign_id', 'adset_id', 'ad_id', 'date_start', 'date_stop',
            'impressions', 'reach', 'clicks', 'inline_link_clicks', 'spend',
            'ctr', 'cpc', 'cpm', 'frequency', 'actions', 'cost_per_action_type',
        ))
        params = {'fields': fields, 'limit': 100}
        if time_range:
            params['time_range'] = time_range
        if date_preset:
            params['date_preset'] = date_preset
        if time_increment:
            params['time_increment'] = time_increment
        payload = self._request('GET', '%s/insights' % ad_id, params=params)
        return payload.get('data') or []
