# -*- coding: utf-8 -*-

import base64
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from ..models.creative_meta import CreativeMetaAccount
from .test_meta_ads import FakeMetaClient


@tagged('post_install', '-at_install')
class TestSimpleMode(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.project = cls.env['project.project'].create({
            'name': 'Proyecto Modo Simple Test',
            'company_id': cls.company.id,
        })
        cls.brief = cls.env['creative.brief'].create({
            'name': 'Brief Modo Simple Test',
            'project_id': cls.project.id,
            'company_id': cls.company.id,
            'objective': 'Generar conversaciones',
            'offer': 'Diagnóstico',
            'target_audience': 'Empresas argentinas',
        })
        cls.creative = cls.env['creative.asset'].create({
            'name': 'Pieza Modo Simple Test',
            'brief_id': cls.brief.id,
            'aspect_ratio': '1:1',
            'placement': 'feed',
        })
        cls.png = base64.b64encode(base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
        ))

    def _enable_simple_mode(self):
        self.env['ir.config_parameter'].sudo().set_param('creative_lab.simple_mode', 'True')

    def _create_version(self):
        return self.env['creative.asset.version'].create({
            'creative_id': self.creative.id,
            'operation': 'import',
            'prompt': 'Imagen de prueba',
            'file': self.png,
            'filename': 'simple-mode.png',
            'mime_type': 'image/png',
        })

    def _publication(self, version, export=False, connection=False):
        return self.env['creative.publication'].create({
            'name': 'Publicación Modo Simple Test',
            'creative_id': self.creative.id,
            'version_id': version.id,
            'export_id': export.id if export else False,
            'meta_connection_id': connection.id if connection else False,
            'primary_text': 'Convertí conversaciones en oportunidades.',
            'headline': 'Más oportunidades reales',
            'welcome_message': 'Hola, quiero coordinar un diagnóstico',
            'budget_type': 'lifetime',
            'lifetime_budget': 50.0,
            'end_at': fields.Datetime.now() + timedelta(days=7),
        })

    def _export_and_connection(self, version):
        export = self.env['creative.asset.export']._create_materialized({
            'name': 'Export Modo Simple Test',
            'version_id': version.id,
            'file': self.png,
            'filename': 'simple-clean.png',
            'mime_type': 'image/png',
            'output_format': 'png',
            'quality': 95,
            'metadata_removed': True,
            'fingerprint': 'simple-%s' % version.id,
        })
        connection = self.env['creative.meta.account'].create({
            'name': 'Meta Simple Test',
            'company_id': self.company.id,
            'ad_account_id': 'act_999999999',
            'page_id': '111111111',
            'whatsapp_phone_number': '+54 9 351 555 1234',
            'publish_enabled': True,
            'max_lifetime_budget': 100.0,
            'max_daily_budget': 20.0,
            'max_campaign_days': 14,
        })
        connection._system_write({
            'connection_state': 'ready',
            'currency_id': self.company.currency_id.id,
            'timezone_name': 'America/Argentina/Cordoba',
        })
        return export, connection

    def test_simple_mode_auto_approves_new_versions(self):
        self._enable_simple_mode()
        version = self._create_version()
        self.assertEqual(version.state, 'approved')
        self.assertEqual(version.approved_by_id, self.env.user)
        self.assertTrue(version.approved_at)
        self.assertEqual(self.creative.current_version_id, version)
        self.assertEqual(self.creative.state, 'approved')

        export_wizard = self.env['creative.asset.export.wizard'].create({
            'version_id': version.id,
            'output_format': 'original',
            'strip_metadata': True,
        })
        action = export_wizard.action_export()
        export = self.env['creative.asset.export'].browse(action['res_id'])
        self.assertEqual(export.version_id, version)
        self.assertTrue(export.metadata_removed)

    def test_default_mode_keeps_review_flow(self):
        self.assertFalse(self.creative.simple_mode)
        version = self._create_version()
        self.assertEqual(version.state, 'draft')
        self.assertEqual(self.creative.state, 'generating')
        export_wizard = self.env['creative.asset.export.wizard'].create({
            'version_id': version.id,
            'output_format': 'original',
            'strip_metadata': True,
        })
        with self.assertRaises(ValidationError):
            export_wizard.action_export()

    def test_prepare_and_publish_runs_in_one_step(self):
        self._enable_simple_mode()
        version = self._create_version()
        export, connection = self._export_and_connection(version)
        publication = self._publication(version, export=export, connection=connection)
        fake = FakeMetaClient()
        with patch.object(CreativeMetaAccount, '_get_client', return_value=fake):
            publication.action_prepare_and_publish()
        self.assertEqual(publication.status, 'paused')
        self.assertEqual(publication.external_ad_id, 'ad-test-id')
        self.assertEqual(publication.external_image_hash, 'image-test-hash')

    def test_prepare_and_publish_propagates_validation_errors(self):
        self._enable_simple_mode()
        version = self._create_version()
        publication = self._publication(version)
        with self.assertRaises(ValidationError):
            publication.action_prepare_and_publish()
        self.assertEqual(publication.status, 'draft')

    def test_prepare_and_publish_requires_simple_mode(self):
        version = self._create_version()
        version.action_submit_review()
        version.action_approve()
        export, connection = self._export_and_connection(version)
        publication = self._publication(version, export=export, connection=connection)
        with self.assertRaises(UserError):
            publication.action_prepare_and_publish()
        self.assertEqual(publication.status, 'draft')

    def test_creative_hint_without_versions(self):
        self.assertEqual(
            self.creative.next_step_hint,
            'Generá la primera versión con el botón Generar / retocar.',
        )
