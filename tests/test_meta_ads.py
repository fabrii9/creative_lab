# -*- coding: utf-8 -*-

import base64
import json
from datetime import timedelta
from unittest.mock import Mock, patch

import requests

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from ..models.creative_meta import CreativeMetaAccount
from ..services.meta_ads import MetaAdsClient, MetaAdsError


class FakeMetaClient:
    def __init__(
        self,
        fail_step=False,
        ambiguous=False,
        existing_steps=None,
        budget_override=None,
    ):
        self.calls = []
        self.fail_step = fail_step
        self.ambiguous = ambiguous
        self.existing_steps = set(existing_steps or [])
        self.budget_override = budget_override
        self.payloads = {}
        self.delivery_statuses = {
            'campaign-test-id': 'PAUSED',
            'adset-test-id': 'PAUSED',
            'ad-test-id': 'PAUSED',
        }

    def _result(self, step, values=False):
        self.calls.append((step, values))
        if self.fail_step == step:
            raise MetaAdsError(
                'Falla controlada', code=100, subcode=200,
                fbtrace_id='trace-test', ambiguous=self.ambiguous,
            )
        self.payloads[step] = values or {}
        return {'id': '%s-test-id' % step}

    def upload_image(self, _account, _raw, _filename):
        self.calls.append(('image', None))
        if self.fail_step == 'image':
            raise MetaAdsError('Falla controlada', ambiguous=self.ambiguous)
        return 'image-test-hash'

    def create_campaign(self, _account, values):
        return self._result('campaign', values)

    def create_adset(self, _account, values):
        return self._result('adset', values)

    def create_creative(self, _account, values):
        return self._result('creative', values)

    def create_ad(self, _account, values):
        return self._result('ad', values)

    def set_status(self, object_id, status):
        self.calls.append(('status', (object_id, status)))
        if self.fail_step == 'status:%s' % object_id:
            raise MetaAdsError('Falla controlada', ambiguous=self.ambiguous)
        self.delivery_statuses[object_id] = status
        return {'success': True}

    def get_delivery_object(self, object_id):
        self.calls.append(('delivery', object_id))
        configured = self.delivery_statuses.get(object_id, 'PAUSED')
        return {
            'id': object_id,
            'configured_status': configured,
            'effective_status': configured,
        }

    def get_campaign(self, campaign_id):
        self.calls.append(('get_campaign', campaign_id))
        values = dict(self.payloads.get('campaign') or {})
        values.update({
            'id': campaign_id,
            'name': values.get('name', ''),
            'configured_status': self.delivery_statuses.get(campaign_id, 'PAUSED'),
            'effective_status': self.delivery_statuses.get(campaign_id, 'PAUSED'),
            'objective': values.get('objective', 'OUTCOME_LEADS'),
            'special_ad_categories': values.get('special_ad_categories', []),
        })
        return values

    def get_adset(self, adset_id):
        self.calls.append(('get_adset', adset_id))
        values = dict(self.payloads.get('adset') or {})
        values.update({
            'id': adset_id,
            'name': values.get('name', ''),
            'campaign_id': values.get('campaign_id', 'campaign-test-id'),
            'configured_status': self.delivery_statuses.get(adset_id, 'PAUSED'),
            'effective_status': self.delivery_statuses.get(adset_id, 'PAUSED'),
        })
        if self.budget_override is not None:
            field_name = 'daily_budget' if 'daily_budget' in values else 'lifetime_budget'
            values[field_name] = self.budget_override
        return values

    def get_ad(self, ad_id):
        self.calls.append(('get_ad', None))
        values = dict(self.payloads.get('ad') or {})
        configured = self.delivery_statuses.get(ad_id, 'ACTIVE')
        values.update({
            'id': ad_id,
            'name': values.get('name', ''),
            'campaign_id': 'campaign-test-id',
            'adset_id': values.get('adset_id', 'adset-test-id'),
            'creative': values.get('creative', {'creative_id': 'creative-test-id'}),
            'configured_status': configured,
            'effective_status': 'PENDING_REVIEW' if configured == 'ACTIVE' else configured,
        })
        creative = values.get('creative')
        if isinstance(creative, dict) and 'creative_id' in creative and 'id' not in creative:
            values['creative'] = {'id': creative['creative_id']}
        return values

    def find_named(self, _account, edge, name):
        self.calls.append(('reconcile', (edge, name)))
        singular = {'campaigns': 'campaign', 'adsets': 'adset', 'adcreatives': 'creative', 'ads': 'ad'}[edge]
        if singular not in self.existing_steps:
            return []
        record = {
            'id': '%s-test-id' % singular,
            'name': name,
        }
        if singular in ('campaign', 'adset', 'ad'):
            record['configured_status'] = 'PAUSED'
        if singular == 'campaign':
            record['objective'] = 'OUTCOME_LEADS'
            record['special_ad_categories'] = []
        elif singular == 'adset':
            record.update({
                'campaign_id': 'campaign-test-id',
                'destination_type': 'WHATSAPP',
            })
        elif singular == 'ad':
            record.update({
                'campaign_id': 'campaign-test-id',
                'adset_id': 'adset-test-id',
                'creative': {'id': 'creative-test-id'},
            })
        return [record]

    def get_insights(self, _ad_id, *, time_range=None, date_preset=None, time_increment=None):
        self.calls.append(('insights', (time_range, date_preset, time_increment)))
        row = {
            'date_start': fields.Date.to_string(fields.Date.today()),
            'date_stop': fields.Date.to_string(fields.Date.today()),
            'spend': '12.34',
            'impressions': '1000',
            'reach': '800',
            'clicks': '41',
            'inline_link_clicks': '35',
            'ctr': '4.1',
            'cpc': '0.30',
            'cpm': '12.34',
            'frequency': '1.25',
            'actions': [
                {'action_type': 'onsite_conversion.messaging_conversation_started_7d', 'value': '3'},
                {'action_type': 'link_click', 'value': '35'},
            ],
            'cost_per_action_type': [
                {'action_type': 'onsite_conversion.messaging_conversation_started_7d', 'value': '4.11'},
            ],
        }
        return [row]


@tagged('post_install', '-at_install')
class TestCreativeMetaAds(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.project = cls.env['project.project'].create({
            'name': 'Proyecto Meta Test',
            'company_id': cls.company.id,
        })
        cls.brief = cls.env['creative.brief'].create({
            'name': 'Brief Meta Test',
            'project_id': cls.project.id,
            'company_id': cls.company.id,
            'objective': 'Generar conversaciones',
            'offer': 'Diagnóstico',
            'target_audience': 'Empresas argentinas',
            'pains': 'No convierten mensajes en ventas',
        })
        cls.creative = cls.env['creative.asset'].create({
            'name': 'Pieza Meta Test',
            'brief_id': cls.brief.id,
            'aspect_ratio': '4:5',
            'placement': 'feed',
        })
        png = base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
        )
        cls.version = cls.env['creative.asset.version'].create({
            'creative_id': cls.creative.id,
            'operation': 'import',
            'prompt': 'Imagen de prueba',
            'file': base64.b64encode(png),
            'filename': 'meta-test.png',
            'mime_type': 'image/png',
        })
        cls.version.action_submit_review()
        cls.version.action_approve()
        cls.export = cls.env['creative.asset.export']._create_materialized({
            'name': 'Export Meta Test',
            'version_id': cls.version.id,
            'file': base64.b64encode(png),
            'filename': 'meta-test-clean.png',
            'mime_type': 'image/png',
            'output_format': 'png',
            'quality': 95,
            'metadata_removed': True,
            'fingerprint': 'meta-test-%s' % cls.version.id,
        })
        cls.connection = cls.env['creative.meta.account'].create({
            'name': 'Meta Test',
            'company_id': cls.company.id,
            'ad_account_id': 'act_123456789',
            'page_id': '987654321',
            'whatsapp_phone_number': '+54 9 351 555 5555',
            'publish_enabled': True,
            'max_lifetime_budget': 100.0,
            'max_daily_budget': 20.0,
            'max_campaign_days': 14,
        })
        cls.connection._system_write({
            'connection_state': 'ready',
            'currency_id': cls.company.currency_id.id,
            'timezone_name': 'America/Argentina/Cordoba',
        })

    def _publication(self):
        return self.env['creative.publication'].create({
            'name': 'Publicación Meta Test',
            'creative_id': self.creative.id,
            'version_id': self.version.id,
            'export_id': self.export.id,
            'meta_connection_id': self.connection.id,
            'primary_text': 'Convertí conversaciones en oportunidades.',
            'headline': 'Más oportunidades reales',
            'description': 'Diagnóstico inicial',
            'welcome_message': 'Hola, quiero coordinar un diagnóstico',
            'budget_type': 'lifetime',
            'lifetime_budget': 50.0,
            'end_at': fields.Datetime.now() + timedelta(days=7),
        })

    def test_context_cannot_forge_remote_fields(self):
        publication = self._publication()
        with self.assertRaises(AccessError):
            publication.with_context(allow_publication_workflow=True).write({'status': 'active'})
        with self.assertRaises(AccessError):
            publication.with_context(allow_publication_workflow=True).write({
                'external_ad_id': 'forged-id',
            })
        with self.assertRaises(UserError):
            self.version.with_context(allow_workflow_write=True).write({'state': 'rejected'})
        with self.assertRaises(AccessError):
            self.creative.with_context(allow_workflow_write=True).write({'state': 'approved'})
        publication.action_prepare()
        with self.assertRaises(ValidationError):
            publication.write({'name': 'Nombre que rompería la conciliación'})

    def test_connection_results_cannot_be_forged_on_create(self):
        with self.assertRaises(AccessError):
            self.env['creative.meta.account'].create({
                'name': 'Conexión forjada',
                'company_id': self.company.id,
                'ad_account_id': '222222',
                'page_id': '333333',
                'whatsapp_phone_number': '+54 9 11 5555 0000',
                'connection_state': 'ready',
                'currency_id': self.company.currency_id.id,
            })

    def test_connection_identity_change_requires_a_new_test(self):
        self.assertEqual(self.connection.connection_state, 'ready')
        self.connection.write({'page_id': '987654322'})
        self.assertEqual(self.connection.connection_state, 'untested')
        self.assertFalse(self.connection.currency_id)

    def test_export_cannot_be_fabricated_over_rpc(self):
        with self.assertRaises(AccessError):
            self.env['creative.asset.export'].create({
                'name': 'Export forjado',
                'version_id': self.version.id,
                'file': self.export.file,
                'filename': 'forged.png',
                'mime_type': 'image/png',
                'output_format': 'png',
                'metadata_removed': True,
                'fingerprint': 'forged-%s' % self.version.id,
            })

    def test_publish_creates_every_remote_object_paused(self):
        publication = self._publication()
        publication.action_prepare()
        fake = FakeMetaClient()
        with patch.object(CreativeMetaAccount, '_get_client', return_value=fake):
            publication.action_publish_paused()

        self.assertEqual(publication.status, 'paused')
        self.assertEqual(publication.external_ad_id, 'ad-test-id')
        self.assertEqual(publication.external_image_hash, 'image-test-hash')
        payloads = dict((step, values) for step, values in fake.calls if values)
        for step in ('campaign', 'adset', 'ad'):
            self.assertEqual(payloads[step]['status'], 'PAUSED')
        self.assertEqual(payloads['adset']['destination_type'], 'WHATSAPP')
        self.assertEqual(payloads['adset']['optimization_goal'], 'CONVERSATIONS')
        self.assertEqual(
            payloads['adset']['targeting']['targeting_automation']['advantage_audience'],
            0,
        )
        self.assertEqual(
            payloads['adset']['promoted_object']['whatsapp_phone_number'],
            '5493515555555',
        )
        link_data = payloads['creative']['object_story_spec']['link_data']
        self.assertEqual(link_data['image_hash'], 'image-test-hash')
        self.assertEqual(
            json.loads(link_data['page_welcome_message'])['text_format']['message']['text'],
            publication.welcome_message,
        )

    def test_failed_step_is_resumable_without_recreating_previous_objects(self):
        publication = self._publication()
        publication.action_prepare()
        failing = FakeMetaClient(fail_step='adset')
        with patch.object(CreativeMetaAccount, '_get_client', return_value=failing):
            publication.action_publish_paused()
        self.assertEqual(publication.status, 'error')
        self.assertTrue(publication.external_campaign_id)
        self.assertFalse(publication.external_adset_id)

        resumed = FakeMetaClient()
        with patch.object(CreativeMetaAccount, '_get_client', return_value=resumed):
            publication.action_publish_paused()
        self.assertEqual(publication.status, 'paused')
        resumed_steps = [item[0] for item in resumed.calls]
        self.assertNotIn('image', resumed_steps)
        self.assertNotIn('campaign', resumed_steps)

    def test_publish_recovers_a_paused_orphan_by_idempotent_name(self):
        publication = self._publication()
        publication.action_prepare()
        fake = FakeMetaClient(existing_steps={'campaign'})
        with patch.object(CreativeMetaAccount, '_get_client', return_value=fake):
            publication.action_publish_paused()

        self.assertEqual(publication.status, 'paused')
        self.assertEqual(publication.external_campaign_id, 'campaign-test-id')
        self.assertFalse(any(step == 'campaign' for step, _values in fake.calls))
        recovered_names = [
            values[1] for step, values in fake.calls
            if step == 'reconcile' and values[0] == 'campaigns'
        ]
        self.assertEqual(recovered_names, [publication._meta_name('Campaña')])

    def test_duplicate_publication_starts_as_a_clean_draft(self):
        publication = self._publication()
        publication.action_prepare()
        with patch.object(CreativeMetaAccount, '_get_client', return_value=FakeMetaClient()):
            publication.action_publish_paused()
        duplicate = publication.copy({'name': 'Nueva variante'})
        self.assertEqual(duplicate.status, 'draft')
        self.assertFalse(duplicate.external_campaign_id)
        self.assertFalse(duplicate.external_adset_id)
        self.assertFalse(duplicate.external_creative_id)
        self.assertFalse(duplicate.external_ad_id)
        self.assertFalse(duplicate.reconcile_required)
        with self.assertRaises(UserError):
            publication.unlink()

    def test_ambiguous_post_blocks_retry(self):
        publication = self._publication()
        publication.action_prepare()
        ambiguous = FakeMetaClient(fail_step='campaign', ambiguous=True)
        with patch.object(CreativeMetaAccount, '_get_client', return_value=ambiguous):
            publication.action_publish_paused()
        self.assertTrue(publication.reconcile_required)
        with patch.object(CreativeMetaAccount, '_get_client', return_value=FakeMetaClient()):
            with self.assertRaises(ValidationError):
                publication.action_publish_paused()
        recovery = FakeMetaClient(existing_steps={'campaign'})
        with patch.object(CreativeMetaAccount, '_get_client', return_value=recovery):
            publication.action_reconcile_meta()
            publication.action_publish_paused()
        self.assertFalse(publication.reconcile_required)
        self.assertEqual(publication.external_campaign_id, 'campaign-test-id')
        self.assertEqual(publication.status, 'paused')

    def test_insights_sync_keeps_meta_conversations_separate(self):
        publication = self._publication()
        publication.action_prepare()
        fake = FakeMetaClient()
        with patch.object(CreativeMetaAccount, '_get_client', return_value=fake):
            publication.action_publish_paused()
            publication.action_sync_meta_metrics()

        self.assertAlmostEqual(publication.spend, 12.34)
        self.assertEqual(publication.impressions, 1000)
        self.assertEqual(publication.inline_link_clicks, 35)
        self.assertEqual(publication.meta_conversation_count, 3)
        self.assertEqual(publication.conversation_count, 0)
        self.assertEqual(len(publication.metric_ids), 1)
        self.assertEqual(publication.remote_effective_status, 'PAUSED')
        with patch.object(CreativeMetaAccount, '_get_client', return_value=fake):
            publication.action_sync_meta_metrics()
        self.assertEqual(len(publication.metric_ids), 1)

    def test_metrics_sync_records_missing_runtime_credential(self):
        publication = self._publication()
        publication.action_prepare()
        with patch.object(CreativeMetaAccount, '_get_client', return_value=FakeMetaClient()):
            publication.action_publish_paused()

        with patch.object(
            CreativeMetaAccount,
            '_get_client',
            side_effect=UserError('Variable de token ausente'),
        ):
            publication.action_sync_meta_metrics()

        self.assertIn('Variable de token ausente', publication.sync_error)
        self.assertFalse(publication.reconcile_required)

    def test_activation_is_separate_and_campaign_is_last(self):
        publication = self._publication()
        publication.action_prepare()
        fake = FakeMetaClient()
        with patch.object(CreativeMetaAccount, '_get_client', return_value=fake):
            publication.action_publish_paused()
            with self.assertRaises(ValidationError):
                publication.action_activate()
            self.connection.write({'activation_enabled': True})
            fake.calls.clear()
            publication.action_activate()
            self.assertTrue(publication.delivery_pending)
            self.assertEqual(publication.status, 'paused')
            self.env['creative.publication']._cron_process_meta_commands()

        status_calls = [values for step, values in fake.calls if step == 'status']
        self.assertEqual(status_calls, [
            (publication.external_ad_id, 'ACTIVE'),
            (publication.external_adset_id, 'ACTIVE'),
            (publication.external_campaign_id, 'ACTIVE'),
        ])
        self.assertEqual(publication.status, 'active')
        self.assertEqual(publication.remote_effective_status, 'PENDING_REVIEW')

    def test_activation_blocks_remote_budget_edits_and_pauses_parent(self):
        publication = self._publication()
        publication.action_prepare()
        fake = FakeMetaClient()
        with patch.object(CreativeMetaAccount, '_get_client', return_value=fake):
            publication.action_publish_paused()
            self.connection.write({'activation_enabled': True})
            fake.budget_override = '999999'
            fake.calls.clear()
            publication.action_activate()
            self.env['creative.publication']._cron_process_meta_commands()

        self.assertEqual(publication.status, 'paused')
        self.assertFalse(publication.delivery_pending)
        self.assertTrue(publication.reconcile_required)
        self.assertIn('presupuesto remoto', publication.sync_error)
        self.assertIn(
            ('status', (publication.external_campaign_id, 'PAUSED')),
            fake.calls,
        )

    def test_delivery_reconcile_survives_metrics_sync_and_resolves_safe_parent(self):
        publication = self._publication()
        publication.action_prepare()
        initial = FakeMetaClient()
        with patch.object(CreativeMetaAccount, '_get_client', return_value=initial):
            publication.action_publish_paused()
        self.connection.write({'activation_enabled': True})
        failing = initial
        failing.fail_step = 'status:%s' % publication.external_adset_id
        failing.ambiguous = True
        with patch.object(CreativeMetaAccount, '_get_client', return_value=failing):
            publication.action_activate()
            self.env['creative.publication']._cron_process_meta_commands()
        self.assertTrue(publication.reconcile_required)
        self.assertEqual(publication.reconcile_mode, 'delivery')

        with patch.object(CreativeMetaAccount, '_get_client', return_value=failing):
            publication.action_sync_meta_metrics()
        self.assertTrue(publication.reconcile_required)

        with patch.object(CreativeMetaAccount, '_get_client', return_value=failing):
            publication.action_reconcile_meta()
        self.assertFalse(publication.reconcile_required)
        self.assertEqual(publication.status, 'paused')


@tagged('post_install', '-at_install')
class TestMetaAdsClient(TransactionCase):

    def test_error_redacts_token_and_exposes_structured_fields(self):
        client = MetaAdsClient('super-secret-token')
        response = Mock()
        response.status_code = 400
        response.headers = {}
        response.json.return_value = {
            'error': {
                'message': 'token super-secret-token is invalid',
                'code': 190,
                'error_subcode': 463,
                'fbtrace_id': 'trace-1',
            },
        }
        client.session.request = Mock(return_value=response)
        with self.assertRaises(MetaAdsError) as caught:
            client.get_account('123')
        self.assertNotIn('super-secret-token', str(caught.exception))
        self.assertEqual(caught.exception.code, '190')
        self.assertEqual(caught.exception.subcode, '463')

    def test_post_transport_error_is_ambiguous(self):
        client = MetaAdsClient('secret')
        client.session.request = Mock(side_effect=requests.Timeout('timed out'))
        with self.assertRaises(MetaAdsError) as caught:
            client.create_campaign('123', {'name': 'Test', 'status': 'PAUSED'})
        self.assertTrue(caught.exception.ambiguous)

    def test_appsecret_proof_is_redacted_from_transport_errors(self):
        client = MetaAdsClient('token-value', app_secret='app-secret-value')
        proof = client._appsecret_proof()
        client.session.request = Mock(side_effect=requests.Timeout(
            'https://graph.facebook.com/?appsecret_proof=%s' % proof
        ))
        with self.assertRaises(MetaAdsError) as caught:
            client.get_account('123')
        rendered = str(caught.exception)
        self.assertNotIn('token-value', rendered)
        self.assertNotIn('app-secret-value', rendered)
        self.assertNotIn(proof, rendered)

    def test_false_status_response_is_rejected(self):
        client = MetaAdsClient('secret')
        response = Mock()
        response.status_code = 200
        response.headers = {}
        response.json.return_value = {'success': False}
        client.session.request = Mock(return_value=response)
        with self.assertRaises(MetaAdsError) as caught:
            client.set_status('123', 'ACTIVE')
        self.assertTrue(caught.exception.ambiguous)

    def test_post_server_error_is_ambiguous(self):
        client = MetaAdsClient('secret')
        response = Mock()
        response.status_code = 500
        response.headers = {}
        response.json.return_value = {
            'error': {'message': 'Temporary server failure', 'code': 1, 'is_transient': True},
        }
        client.session.request = Mock(return_value=response)
        with self.assertRaises(MetaAdsError) as caught:
            client.create_campaign('123', {'name': 'Test', 'status': 'PAUSED'})
        self.assertTrue(caught.exception.ambiguous)
