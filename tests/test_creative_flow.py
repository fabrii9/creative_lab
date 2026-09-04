# -*- coding: utf-8 -*-

import base64
import hashlib
from types import SimpleNamespace
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from ..services.llm_bridge import CreativeLLMBridge


@tagged('post_install', '-at_install')
class TestCreativeFlow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.project = cls.env['project.project'].create({
            'name': 'Proyecto Creative Lab Test',
            'company_id': cls.company.id,
        })
        cls.brief = cls.env['creative.brief'].create({
            'name': 'Campaña mensajes de prueba',
            'project_id': cls.project.id,
            'company_id': cls.company.id,
            'objective': 'Conseguir conversaciones calificadas',
            'offer': 'Diagnóstico inicial',
            'target_audience': 'Responsables de marketing de pymes',
            'pains': 'No pueden atribuir ventas a sus anuncios',
            'brand_guidelines': 'Usar turquesa solo como acento.',
        })
        cls.hypothesis = cls.env['creative.hypothesis'].create({
            'name': 'El costo oculto de no medir',
            'brief_id': cls.brief.id,
            'segment': 'Responsables de marketing',
            'pain': 'No conocen el retorno real',
            'awareness_level': 'problem',
            'sophistication_level': '3',
            'angle': 'Mostrar el costo de decidir a ciegas',
        })
        cls.creative = cls.env['creative.asset'].create({
            'name': 'Creativo atribución 1:1',
            'brief_id': cls.brief.id,
            'hypothesis_id': cls.hypothesis.id,
            'aspect_ratio': '1:1',
            'placement': 'feed',
        })
        cls.image_agent = cls.env.ref('creative_lab.agente_visual_simulacion')

    def _generate(self, prompt, source=False, operation='initial'):
        wizard = self.env['creative.generate.wizard'].create({
            'creative_id': self.creative.id,
            'operation': operation,
            'source_version_id': source.id if source else False,
            'agent_profile_id': self.image_agent.id,
            'prompt': prompt,
        })
        action = wizard.action_generate()
        return self.env['creative.asset.version'].browse(action['res_id'])

    def test_complete_simulated_flow(self):
        with self.assertRaises(AccessError):
            self.brief.write({'state': 'ready'})
        self.brief.action_mark_ready()
        self.assertEqual(self.brief.state, 'ready')
        self.hypothesis.action_select()

        strategy_wizard = self.env['creative.agent.run.wizard'].create({
            'brief_id': self.brief.id,
            'profile_id': self.env.ref('creative_lab.agente_estratega_simulacion').id,
            'operation': 'strategy',
            'prompt': 'Proponé tres ángulos separados por nivel de conciencia.',
        })
        strategy_action = strategy_wizard.action_run()
        strategy_run = self.env['creative.agent.run'].browse(strategy_action['res_id'])
        self.assertEqual(strategy_run.status, 'succeeded')
        self.assertTrue(strategy_run.output_json)
        self.assertIn(
            'Usar turquesa solo como acento.',
            CreativeLLMBridge(self.env)._render_prompt(strategy_run),
        )
        with self.assertRaises(AccessError):
            strategy_run.write({'output_text': 'Resultado manipulado'})

        root = self._generate('Una persona mirando métricas inconexas')
        self.assertEqual((root.width, root.height), (1080, 1080))
        with self.assertRaises(AccessError):
            self.creative.write({'state': 'approved'})
        branch_a = self._generate(
            'Conservar la composición y enfatizar el costo por venta',
            source=root,
            operation='edit',
        )
        branch_b = self._generate(
            'Conservar la composición y enfatizar conversaciones calificadas',
            source=root,
            operation='variation',
        )

        self.assertEqual(len(self.creative.version_ids), 3)
        self.assertEqual(branch_a.parent_id, root)
        self.assertEqual(branch_b.parent_id, root)
        self.assertEqual(branch_b.provider_snapshot, 'simulation')
        self.assertTrue(branch_b.sha256)
        self.assertEqual(
            branch_b.sha256,
            hashlib.sha256(base64.b64decode(branch_b.file)).hexdigest(),
        )

        with self.assertRaises(UserError):
            root.write({'prompt': 'Intento de mutación'})
        with self.assertRaises(UserError):
            root.unlink()

        branch_b.action_submit_review()
        branch_b.action_approve()
        self.assertEqual(branch_b.state, 'approved')
        self.assertEqual(self.creative.current_version_id, branch_b)
        self.assertEqual(self.creative.state, 'approved')

        branch_c = self._generate(
            'Abrir una rama nueva para continuar iterando',
            source=branch_b,
            operation='variation',
        )
        self.assertEqual(branch_c.parent_id, branch_b)
        self.assertEqual(self.creative.current_version_id, branch_c)
        self.assertEqual(self.creative.state, 'generating')

        export_wizard = self.env['creative.asset.export.wizard'].create({
            'version_id': branch_b.id,
            'output_format': 'original',
            'strip_metadata': True,
        })
        export_action = export_wizard.action_export()
        exported = self.env['creative.asset.export'].browse(export_action['res_id'])
        self.assertEqual(exported.version_id, branch_b)
        self.assertTrue(exported.metadata_removed)
        self.assertEqual(exported.mime_type, 'image/svg+xml')
        self.assertTrue(exported.file)

        publication = self.env['creative.publication'].create({
            'name': 'Meta test · Creative Lab',
            'creative_id': self.creative.id,
            'version_id': branch_b.id,
            'daily_budget': 25.0,
        })
        with self.assertRaises(AccessError):
            publication.write({'status': 'active'})
        publication.action_prepare()
        publication.external_ad_id = 'meta-ad-test-001'
        publication.action_activate()
        self.assertEqual(publication.status, 'active')

        self.env['creative.outcome'].create([
            {
                'name': 'Conversación 1',
                'publication_id': publication.id,
                'event_type': 'conversation',
                'source': 'whatsapp',
                'confirmed': True,
            },
            {
                'name': 'Lead calificado 1',
                'publication_id': publication.id,
                'event_type': 'qualified',
                'source': 'crm',
                'confirmed': True,
            },
            {
                'name': 'Venta 1',
                'publication_id': publication.id,
                'event_type': 'sale',
                'source': 'crm',
                'amount': 500.0,
                'confirmed': True,
            },
        ])
        publication.invalidate_recordset()
        self.assertEqual(publication.conversation_count, 1)
        self.assertEqual(publication.qualified_count, 1)
        self.assertEqual(publication.sale_count, 1)
        self.assertEqual(publication.attributed_revenue, 500.0)

    def test_brief_requires_minimum_context(self):
        incomplete = self.env['creative.brief'].create({
            'name': 'Incompleto',
            'project_id': self.project.id,
            'company_id': self.company.id,
        })
        with self.assertRaises(ValidationError):
            incomplete.action_mark_ready()

    def test_parent_must_belong_to_same_creative(self):
        root = self._generate('Raíz')
        other = self.env['creative.asset'].create({
            'name': 'Otro creativo',
            'brief_id': self.brief.id,
        })
        with self.assertRaises(ValidationError):
            self.env['creative.asset.version'].create({
                'creative_id': other.id,
                'parent_id': root.id,
                'operation': 'edit',
                'prompt': 'Cruce inválido',
                'file': root.file,
                'filename': root.filename,
            })

    def test_initial_file_prefills_first_generation(self):
        encoded = base64.b64encode(b'archivo-inicial-de-prueba')
        self.brief.write({
            'initial_file': encoded,
            'initial_filename': 'referencia.png',
        })
        defaults = self.env['creative.generate.wizard'].with_context(
            default_creative_id=self.creative.id,
        ).default_get([
            'creative_id',
            'source_version_id',
            'input_file',
            'input_filename',
        ])
        self.assertEqual(defaults['input_file'], encoded)
        self.assertEqual(defaults['input_filename'], 'referencia.png')

    def test_visual_analysis_builds_multimodal_request(self):
        captured = {}

        class FakeProvider:
            provider_type = 'openai'
            name = 'OpenAI de prueba'
            model = 'vision-test'

            def chat_completion(self, messages, **kwargs):
                captured['messages'] = messages
                captured['kwargs'] = kwargs
                return '{"verdict": "ok"}'

        profile = SimpleNamespace(
            system_prompt='Revisá el anuncio.',
            model_override=False,
            temperature=0.2,
            max_tokens=300,
        )
        source = SimpleNamespace(file=False, mime_type=False, filename=False)
        run = SimpleNamespace(
            input_file=base64.b64encode(b'png-de-prueba'),
            input_mime_type='image/png',
            input_filename='anuncio.png',
            source_version_id=source,
        )
        result = CreativeLLMBridge(self.env)._analyze_image(
            FakeProvider(), profile, run, 'Evaluá legibilidad y cumplimiento.'
        )
        self.assertEqual(result['text'], '{"verdict": "ok"}')
        user_content = captured['messages'][-1]['content']
        self.assertEqual(user_content[0]['type'], 'text')
        self.assertEqual(user_content[1]['type'], 'image_url')
        self.assertTrue(user_content[1]['image_url']['url'].startswith('data:image/png;base64,'))

    def test_simulator_respects_portrait_aspect_ratios(self):
        self.creative.aspect_ratio = '4:5'
        feed = self._generate('Composición editorial para feed')
        self.assertEqual((feed.width, feed.height), (1080, 1350))

        self.creative.aspect_ratio = '9:16'
        story = self._generate('Composición editorial para stories')
        self.assertEqual((story.width, story.height), (1080, 1920))

    def _provider_profile(self, **overrides):
        provider = self.env['llm.provider'].create({
            'name': 'OpenAI guardrails test',
            'provider_type': 'openai',
            'api_key': 'test-key-never-sent',
            'model': 'model-test',
            'company_id': self.company.id,
        })
        values = {
            'name': 'Agente real de prueba',
            'company_id': self.company.id,
            'role': 'strategist',
            'task_type': 'text',
            'execution_mode': 'provider',
            'llm_provider_id': provider.id,
            'system_prompt': 'Respondé con JSON.',
            'output_format': 'json',
            'output_schema': '{"result":{"name":"...","score":0}}',
            'max_tokens': 1_000,
            'max_cost_usd': 0.05,
            'input_cost_per_million': 2.0,
            'output_cost_per_million': 12.0,
        }
        values.update(overrides)
        return self.env['creative.agent.profile'].create(values)

    def _agent_run(self, profile):
        return self.env['creative.agent.run'].create({
            'profile_id': profile.id,
            'company_id': self.company.id,
            'brief_id': self.brief.id,
            'operation': 'strategy',
            'input_prompt': 'Generá una propuesta corta.',
        })

    def test_provider_call_is_blocked_without_pricing(self):
        profile = self._provider_profile(
            input_cost_per_million=0.0,
            output_cost_per_million=0.0,
            fixed_cost_usd=0.0,
        )
        run = self._agent_run(profile)
        with patch.object(CreativeLLMBridge, 'execute') as execute:
            run._execute()
        execute.assert_not_called()
        self.assertEqual(run.status, 'failed')
        self.assertIn('tarifas', run.error_message)

    def test_provider_call_is_blocked_when_preflight_exceeds_budget(self):
        profile = self._provider_profile(
            max_cost_usd=0.001,
            output_cost_per_million=12.0,
        )
        run = self._agent_run(profile)
        with patch.object(CreativeLLMBridge, 'execute') as execute:
            run._execute()
        execute.assert_not_called()
        self.assertEqual(run.status, 'failed')
        self.assertIn('supera el máximo', run.error_message)

    def test_image_call_requires_a_fixed_cost_estimate(self):
        profile = self._provider_profile(
            role='image_generator',
            task_type='image',
            output_format='binary',
            output_schema=False,
            fixed_cost_usd=0.0,
        )
        run = self.env['creative.agent.run'].create({
            'profile_id': profile.id,
            'company_id': self.company.id,
            'brief_id': self.brief.id,
            'creative_id': self.creative.id,
            'operation': 'initial',
            'input_prompt': 'Generá una imagen de prueba.',
        })
        with patch.object(CreativeLLMBridge, 'execute') as execute:
            run._execute()
        execute.assert_not_called()
        self.assertEqual(run.status, 'failed')
        self.assertIn('costo fijo conservador', run.error_message)

    def test_json_output_is_validated_against_example_schema(self):
        profile = self._provider_profile()
        run = self._agent_run(profile)
        response = {
            'text': '{"result":{"name":"Variante A"}}',
            'provider': 'OpenAI guardrails test',
            'model': 'model-test',
        }
        with patch.object(CreativeLLMBridge, 'execute', return_value=response):
            run._execute()
        self.assertEqual(run.status, 'failed')
        self.assertIn('$.result.score', run.error_message)

    def test_json_schema_subset_accepts_a_valid_response(self):
        profile = self._provider_profile(output_schema='''{
            "type": "object",
            "required": ["verdict", "score"],
            "properties": {
                "verdict": {"type": "string", "enum": ["approve", "revise"]},
                "score": {"type": "number"}
            },
            "additionalProperties": false
        }''')
        run = self._agent_run(profile)
        response = {
            'text': '{"verdict":"approve","score":9}',
            'provider': 'OpenAI guardrails test',
            'model': 'model-test',
        }
        with patch.object(CreativeLLMBridge, 'execute', return_value=response):
            run._execute()
        self.assertEqual(run.status, 'succeeded')
        self.assertEqual(run.output_json['verdict'], 'approve')
        self.assertGreater(run.estimated_cost, 0)

    def test_reported_cost_over_limit_rejects_result(self):
        profile = self._provider_profile(max_cost_usd=0.05)
        run = self._agent_run(profile)
        response = {
            'text': '{"result":{"name":"Variante A","score":8}}',
            'provider': 'OpenAI guardrails test',
            'model': 'model-test',
            'cost': 0.08,
        }
        with patch.object(CreativeLLMBridge, 'execute', return_value=response):
            run._execute()
        self.assertEqual(run.status, 'failed')
        self.assertEqual(run.estimated_cost, 0.08)
        self.assertIn('supera el máximo', run.error_message)

    def test_output_schema_must_be_valid_json(self):
        with self.assertRaises(ValidationError):
            self.env['creative.agent.profile'].create({
                'name': 'Esquema inválido',
                'company_id': self.company.id,
                'system_prompt': 'Test',
                'output_format': 'json',
                'output_schema': '{invalid',
            })

    def test_non_finite_json_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env['creative.agent.run']._parse_json('{"score": NaN}')

    def test_example_with_type_key_is_not_misread_as_json_schema(self):
        profile = self._provider_profile(
            output_schema='{"type":"ad","headline":"..."}',
        )
        run = self._agent_run(profile)
        response = {
            'text': '{"type":"campaign","headline":"Una propuesta"}',
            'provider': 'OpenAI guardrails test',
            'model': 'model-test',
        }
        with patch.object(CreativeLLMBridge, 'execute', return_value=response):
            run._execute()
        self.assertEqual(run.status, 'succeeded')

    def test_simulation_allows_zero_budget_and_role_specific_schemas(self):
        for xmlid, expected_key in (
            ('creative_lab.agente_director_simulacion', 'concepts'),
            ('creative_lab.agente_revisor_simulacion', 'verdict'),
        ):
            profile = self.env.ref(xmlid)
            profile.max_cost_usd = 0.0
            run = self.env['creative.agent.run'].create({
                'profile_id': profile.id,
                'company_id': self.company.id,
                'brief_id': self.brief.id,
                'creative_id': self.creative.id,
                'operation': 'review' if profile.role == 'reviewer' else 'analysis',
                'input_prompt': 'Validá el flujo simulado.',
            })
            run._execute()
            self.assertEqual(run.status, 'succeeded', run.error_message)
            self.assertIn(expected_key, run.output_json)
