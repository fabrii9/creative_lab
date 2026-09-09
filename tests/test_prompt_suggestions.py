# -*- coding: utf-8 -*-

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


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

    def _wizard(self, **values):
        defaults = {
            'creative_id': self.creative.id,
            'operation': 'initial',
        }
        defaults.update(values)
        return self.env['creative.generate.wizard'].create(defaults)

    def _last_suggestion_run(self):
        return self.env['creative.agent.run'].search(
            [('creative_id', '=', self.creative.id)],
            order='id desc',
            limit=1,
        )

    def test_suggest_prompt_fills_field_and_audits_run(self):
        wizard = self._wizard()
        wizard.action_suggest_prompt()
        run = self._last_suggestion_run()
        self.assertEqual(run.status, 'succeeded', run.error_message)
        self.assertEqual(wizard.prompt, run.output_text.strip())
        self.assertIn('Conseguir conversaciones calificadas', run.input_prompt)

    def test_suggest_prompt_improves_existing_draft(self):
        wizard = self._wizard(prompt='persona con gráficos')
        wizard.action_suggest_prompt()
        run = self._last_suggestion_run()
        self.assertIn('persona con gráficos', run.input_prompt)
        self.assertTrue(wizard.prompt)

    def test_suggest_negative_prompt_fills_field(self):
        wizard = self._wizard()
        wizard.action_suggest_negative_prompt()
        run = self._last_suggestion_run()
        self.assertEqual(run.status, 'succeeded', run.error_message)
        self.assertEqual(wizard.negative_prompt, run.output_text.strip())

    def test_suggestion_requires_a_text_agent(self):
        text_agents = self.env['creative.agent.profile'].search([
            ('task_type', '=', 'text'),
            ('company_id', '=', self.company.id),
        ])
        text_agents.write({'active': False})
        wizard = self._wizard()
        with self.assertRaises(ValidationError):
            wizard.action_suggest_prompt()

    def test_suggest_headline_fills_creative_copy(self):
        self.creative.action_suggest_headline()
        run = self.env['creative.agent.run'].search(
            [('creative_id', '=', self.creative.id)],
            order='id desc',
            limit=1,
        )
        self.assertEqual(run.status, 'succeeded', run.error_message)
        self.assertEqual(self.creative.headline, run.output_text.strip())
        self.assertIn('Diagnóstico inicial', run.input_prompt)

    def test_suggest_primary_text_improves_existing_draft(self):
        self.creative.primary_text = 'Medí tus anuncios'
        self.creative.action_suggest_primary_text()
        run = self.env['creative.agent.run'].search(
            [('creative_id', '=', self.creative.id)],
            order='id desc',
            limit=1,
        )
        self.assertIn('Medí tus anuncios', run.input_prompt)
        self.assertTrue(self.creative.primary_text)
