# -*- coding: utf-8 -*-

import base64
from types import SimpleNamespace
from unittest.mock import Mock, patch

from odoo.tests import TransactionCase, tagged

from ..services import llm_bridge as llm_bridge_module
from ..services.llm_bridge import CreativeLLMBridge


@tagged('post_install', '-at_install')
class TestLLMBridgeImages(TransactionCase):

    def test_render_prompt_includes_configured_json_schema(self):
        schema = '{"angles":[{"name":"...","rationale":"..."}]}'
        profile = SimpleNamespace(
            output_format='json',
            output_schema=schema,
            prompt_template='Pedido: {prompt}',
            system_prompt='Sos estratega.',
            task_type='text',
        )
        run = SimpleNamespace(
            brief_id=False,
            creative_id=SimpleNamespace(hypothesis_id=False, name='Creativo de prueba'),
            input_prompt='Proponé dos ángulos.',
            profile_id=profile,
        )

        rendered = CreativeLLMBridge(self.env)._render_prompt(run)

        self.assertIn('Pedido: Proponé dos ángulos.', rendered)
        self.assertIn('Respondé exclusivamente con JSON válido', rendered)
        self.assertTrue(rendered.endswith(schema))

        profile.output_format = 'text'
        self.assertNotIn(schema, CreativeLLMBridge(self.env)._render_prompt(run))

    def _provider(self, model):
        return SimpleNamespace(
            api_key='test-key',
            base_url='https://images.example.test/v1',
            model=model,
            name='OpenAI de prueba',
            provider_type='openai',
            timeout=99,
        )

    def _profile(self, *, quality='high', size='1536x1024', timeout=37):
        return SimpleNamespace(
            image_quality=quality,
            image_size=size,
            model_override=False,
            timeout=timeout,
        )

    def _run(self, aspect_ratio, source=False):
        empty_source = SimpleNamespace(file=False, filename=False, mime_type=False)
        return SimpleNamespace(
            creative_id=SimpleNamespace(aspect_ratio=aspect_ratio),
            idempotency_key='12345678-test',
            input_file=base64.b64encode(b'source-image') if source else False,
            input_filename='source.png' if source else False,
            input_mime_type='image/png' if source else False,
            source_version_id=empty_source,
        )

    @staticmethod
    def _image_response():
        response = Mock()
        response.headers = {'x-request-id': 'req-image-test'}
        response.json.return_value = {
            'data': [{'b64_json': base64.b64encode(b'generated-image').decode('ascii')}],
        }
        return response

    def test_gpt_image_generation_uses_aspect_ratio_quality_and_timeout(self):
        expected_sizes = {
            '1:1': '1024x1024',
            '4:5': '1024x1280',
            '9:16': '1152x2048',
            '1.91:1': '1792x944',
        }
        bridge = CreativeLLMBridge(self.env)
        profile = self._profile(quality='medium', timeout=43)

        with patch.object(llm_bridge_module.requests, 'post') as post:
            post.return_value = self._image_response()
            for aspect_ratio, expected_size in expected_sizes.items():
                with self.subTest(aspect_ratio=aspect_ratio):
                    post.reset_mock()
                    result = bridge._generate_openai_image(
                        self._provider('gpt-image-2'),
                        profile,
                        self._run(aspect_ratio),
                        'Generá el anuncio',
                    )
                    request = post.call_args
                    self.assertEqual(request.args[0], 'https://images.example.test/v1/images/generations')
                    self.assertEqual(request.kwargs['timeout'], 43)
                    self.assertEqual(request.kwargs['json']['size'], expected_size)
                    self.assertEqual(request.kwargs['json']['quality'], 'medium')
                    self.assertNotIn('response_format', request.kwargs['json'])
                    self.assertEqual(result['file'], base64.b64encode(b'generated-image').decode('ascii'))

    def test_gpt_image_edit_omits_legacy_response_format(self):
        bridge = CreativeLLMBridge(self.env)

        with patch.object(llm_bridge_module.requests, 'post') as post:
            post.return_value = self._image_response()
            bridge._generate_openai_image(
                self._provider('gpt-image-2'),
                self._profile(quality='low', timeout=51),
                self._run('9:16', source=True),
                'Retocá el anuncio',
            )

        request = post.call_args
        self.assertEqual(request.args[0], 'https://images.example.test/v1/images/edits')
        self.assertEqual(request.kwargs['timeout'], 51)
        self.assertEqual(request.kwargs['data']['size'], '1152x2048')
        self.assertEqual(request.kwargs['data']['quality'], 'low')
        self.assertNotIn('response_format', request.kwargs['data'])
        self.assertEqual(request.kwargs['files']['image'][1], b'source-image')

    def test_earlier_gpt_image_keeps_standard_profile_size(self):
        bridge = CreativeLLMBridge(self.env)

        with patch.object(llm_bridge_module.requests, 'post') as post:
            post.return_value = self._image_response()
            bridge._generate_openai_image(
                self._provider('gpt-image-1'),
                self._profile(quality='high', size='1024x1536'),
                self._run('9:16'),
                'Generá el anuncio',
            )

        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['size'], '1024x1536')
        self.assertEqual(payload['quality'], 'high')
        self.assertNotIn('response_format', payload)

    def test_legacy_image_model_keeps_profile_size_and_response_format(self):
        bridge = CreativeLLMBridge(self.env)

        with patch.object(llm_bridge_module.requests, 'post') as post:
            post.return_value = self._image_response()
            bridge._generate_openai_image(
                self._provider('dall-e-3'),
                self._profile(size='1536x1024', timeout=29),
                self._run('9:16'),
                'Generá el anuncio',
            )

        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['size'], '1536x1024')
        self.assertEqual(payload['response_format'], 'b64_json')
        self.assertNotIn('quality', payload)
        self.assertEqual(post.call_args.kwargs['timeout'], 29)
