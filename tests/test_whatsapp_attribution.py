# -*- coding: utf-8 -*-

import base64

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestWhatsappAttribution(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.project = cls.env['project.project'].create({
            'name': 'Proyecto atribución test',
            'company_id': cls.company.id,
        })
        cls.brief = cls.env['creative.brief'].create({
            'name': 'Brief atribución',
            'project_id': cls.project.id,
            'company_id': cls.company.id,
            'objective': 'Conversaciones',
            'offer': 'Diagnóstico',
            'target_audience': 'PyMEs',
        })
        cls.creative = cls.env['creative.asset'].create({
            'name': 'Creativo atribución',
            'brief_id': cls.brief.id,
        })
        png = base64.b64encode(base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
        ))
        cls.version = cls.env['creative.asset.version'].create({
            'creative_id': cls.creative.id,
            'operation': 'import',
            'prompt': 'Imagen de prueba',
            'file': png,
            'filename': 'atribucion.png',
            'mime_type': 'image/png',
        })
        cls.publication = cls.env['creative.publication'].create({
            'name': 'Publicación atribución test',
            'creative_id': cls.creative.id,
            'version_id': cls.version.id,
        })
        cls.publication._system_write({'external_ad_id': 'ad-atribucion-123'})
        cls.wa_account = cls.env['whatsapp.account'].create({
            'name': 'Cuenta WA test',
            'app_uid': 'app-test',
            'app_secret': 'secret-test',
            'account_uid': 'account-test',
            'phone_uid': 'phone-test',
            'token': 'token-test',
            'notify_user_id': cls.env.user.id,
        })

    def _inbound_message(self, msg_uid):
        mail_message = self.env['mail.message'].create({
            'body': 'Hola, vi el anuncio',
            'message_type': 'comment',
        })
        return self.env['whatsapp.message'].create({
            'mail_message_id': mail_message.id,
            'message_type': 'inbound',
            'mobile_number': '+5493515551234',
            'msg_uid': msg_uid,
            'state': 'received',
            'wa_account_id': self.wa_account.id,
        })

    def _capture(self, msg_uid, source_id):
        self.wa_account._creative_lab_capture_referrals({
            'messages': [{
                'id': msg_uid,
                'from': '5493515551234',
                'type': 'text',
                'text': {'body': 'Hola'},
                'referral': {
                    'source_id': source_id,
                    'source_url': 'https://fb.me/anuncio-test',
                    'source_type': 'ad',
                    'ctwa_clid': 'clid-test',
                },
            }],
        })

    def test_referral_creates_confirmed_outcome(self):
        message = self._inbound_message('wamid-test-1')
        self._capture('wamid-test-1', 'ad-atribucion-123')

        self.assertEqual(message.referral_source_id, 'ad-atribucion-123')
        self.assertEqual(message.referral_ctwa_clid, 'clid-test')
        outcome = self.env['creative.outcome'].search([
            ('whatsapp_message_id', '=', 'wamid-test-1'),
        ])
        self.assertEqual(len(outcome), 1)
        self.assertEqual(outcome.publication_id, self.publication)
        self.assertEqual(outcome.event_type, 'conversation')
        self.assertEqual(outcome.source, 'whatsapp')
        self.assertTrue(outcome.confirmed)
        self.assertEqual(outcome.referral_ad_id, 'ad-atribucion-123')
        self.assertEqual(self.publication.conversation_count, 1)

    def test_unknown_ad_id_does_not_create_outcome(self):
        message = self._inbound_message('wamid-test-2')
        self._capture('wamid-test-2', 'ad-desconocido-999')

        self.assertEqual(message.referral_source_id, 'ad-desconocido-999')
        self.assertFalse(self.env['creative.outcome'].search([
            ('whatsapp_message_id', '=', 'wamid-test-2'),
        ]))

    def test_same_message_is_not_attributed_twice(self):
        self._inbound_message('wamid-test-3')
        self._capture('wamid-test-3', 'ad-atribucion-123')
        self._capture('wamid-test-3', 'ad-atribucion-123')

        outcomes = self.env['creative.outcome'].search([
            ('whatsapp_message_id', '=', 'wamid-test-3'),
        ])
        self.assertEqual(len(outcomes), 1)
