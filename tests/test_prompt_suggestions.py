# -*- coding: utf-8 -*-

import base64
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from ..services.llm_bridge import CreativeLLMBridge

SUGGESTION_RESPONSE = {
    'text': '{"prompt": "Un taller ordenado con luz cálida", '
            '"negative_prompt": "texto borroso, marcas de agua"}',
    'provider': 'simulation',
    'model': 'test-model',
}

COPY_RESPONSE = {
    'text': '{"headline": "Dejá de adivinar tus números", '
            '"primary_text": "Un solo sistema para stock, ventas y caja.", '
            '"call_to_action": "Pedir diagnóstico"}',
    'provider': 'simulation',
    'model': 'test-model',
}

AD_RESPONSE = {
    'text': '{"headline": "Tu stock, en tiempo real", '
            '"description": "Diagnóstico gratis de 45 minutos", '
            '"primary_text": "Un solo sistema para stock, ventas y caja."}',
    'provider': 'simulation',
    'model': 'test-model',
}


@tagged('post_install', '-at_install')
class TestPromptSuggestions(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.project = cls.env['project.project'].create({
            'name': 'Proyecto sugerencias test',
            'company_id': cls.company.id,
        })
        cls.brief = cls.env['creative.brief'].create({
            'name': 'Brief sugerencias',
            'project_id': cls.project.id,
            'company_id': cls.company.id,
            'objective': 'Conseguir conversaciones calificadas',
            'offer': 'Diagnóstico inicial',
            'target_audience': 'Responsables de marketing de pymes',
        })
        cls.creative = cls.env['creative.asset'].create({
            'name': 'Creativo sugerencias',
            'brief_id': cls.brief.id,
            'aspect_ratio': '1:1',
            'placement': 'feed',
        })
        cls.text_agent = cls.env['creative.agent.profile'].create({
            'name': 'Redactor sugerencias test',
            'company_id': cls.company.id,
            'role': 'creative_director',
            'task_type': 'text',
            'execution_mode': 'simulation',
            'system_prompt': 'Respondé en JSON.',
            'output_format': 'text',
        })
        cls.env['creative.agent.profile'].search([
            ('task_type', '=', 'text'),
            ('id', '!=', cls.text_agent.id),
        ]).write({'active': False})

    def _wizard(self, **values):
        defaults = {
            'creative_id': self.creative.id,
            'operation': 'initial',
        }
        defaults.update(values)
        return self.env['creative.generate.wizard'].create(defaults)

    def _last_run(self):
        return self.env['creative.agent.run'].search(
            [('profile_id', '=', self.text_agent.id)],
            order='id desc',
            limit=1,
        )

    def test_suggest_all_fills_empty_wizard_fields(self):
        wizard = self._wizard()
        with patch.object(CreativeLLMBridge, 'execute', return_value=SUGGESTION_RESPONSE):
            wizard.action_suggest_prompt()
        self.assertEqual(wizard.prompt, 'Un taller ordenado con luz cálida')
        self.assertEqual(wizard.negative_prompt, 'texto borroso, marcas de agua')
        run = self._last_run()
        self.assertEqual(run.status, 'succeeded', run.error_message)
        self.assertIn('Diagnóstico inicial', run.input_prompt)

    def test_suggest_all_keeps_filled_fields(self):
        wizard = self._wizard(prompt='Mi prompt manual')
        with patch.object(CreativeLLMBridge, 'execute', return_value=SUGGESTION_RESPONSE):
            wizard.action_suggest_prompt()
        self.assertEqual(wizard.prompt, 'Mi prompt manual')
        self.assertEqual(wizard.negative_prompt, 'texto borroso, marcas de agua')

    def test_suggest_all_requires_empty_fields(self):
        wizard = self._wizard(prompt='algo', negative_prompt='algo más')
        with self.assertRaises(ValidationError):
            wizard.action_suggest_prompt()

    def test_suggestion_requires_a_text_agent(self):
        self.env['creative.agent.profile'].search([
            ('task_type', '=', 'text'),
        ]).write({'active': False})
        with self.assertRaises(ValidationError):
            self._wizard().action_suggest_prompt()

    def test_suggest_copy_fills_empty_creative_fields(self):
        with patch.object(CreativeLLMBridge, 'execute', return_value=COPY_RESPONSE):
            self.creative.action_suggest_copy()
        self.assertEqual(self.creative.headline, 'Dejá de adivinar tus números')
        self.assertEqual(
            self.creative.primary_text,
            'Un solo sistema para stock, ventas y caja.',
        )
        self.assertEqual(self.creative.call_to_action, 'Pedir diagnóstico')

    def test_suggest_copy_keeps_existing_copy(self):
        self.creative.headline = 'Titular escrito a mano'
        with patch.object(CreativeLLMBridge, 'execute', return_value=COPY_RESPONSE):
            self.creative.action_suggest_copy()
        self.assertEqual(self.creative.headline, 'Titular escrito a mano')
        self.assertEqual(
            self.creative.primary_text,
            'Un solo sistema para stock, ventas y caja.',
        )

    def _publication(self):
        png = base64.b64encode(base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
        ))
        version = self.env['creative.asset.version'].create({
            'creative_id': self.creative.id,
            'operation': 'import',
            'prompt': 'Imagen de prueba',
            'file': png,
            'filename': 'pub-test.png',
            'mime_type': 'image/png',
        })
        return self.env['creative.publication'].create({
            'name': 'Publicación sugerencias test',
            'creative_id': self.creative.id,
            'version_id': version.id,
        })

    def test_suggest_copy_on_publication_fills_empty_fields(self):
        publication = self._publication()
        with patch.object(CreativeLLMBridge, 'execute', return_value=AD_RESPONSE):
            publication.action_suggest_copy()
        self.assertEqual(publication.headline, 'Tu stock, en tiempo real')
        self.assertEqual(publication.description, 'Diagnóstico gratis de 45 minutos')
        self.assertEqual(
            publication.primary_text,
            'Un solo sistema para stock, ventas y caja.',
        )

    def test_suggest_copy_on_publication_keeps_filled_fields(self):
        publication = self._publication()
        publication.headline = 'Título manual'
        with patch.object(CreativeLLMBridge, 'execute', return_value=AD_RESPONSE):
            publication.action_suggest_copy()
        self.assertEqual(publication.headline, 'Título manual')
        self.assertEqual(publication.description, 'Diagnóstico gratis de 45 minutos')
