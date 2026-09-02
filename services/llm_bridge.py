# -*- coding: utf-8 -*-

import base64
import hashlib
import json
from html import escape

import requests

from odoo import _
from odoo.exceptions import UserError, ValidationError


class CreativeLLMBridge:
    """Puerto único entre Creative Lab y LLM Connector.

    Texto usa exclusivamente la API pública ``llm.provider.generate``. La
    versión actual de LLM Connector no ofrece imágenes; por eso este módulo
    añade un adaptador acotado para los endpoints públicos de OpenAI/Gemini.
    """

    OPENAI_COMPATIBLE = {'openai', 'custom'}
    VISION_OPENAI_COMPATIBLE = {'openai', 'kimi', 'kimi_code', 'groq', 'custom'}
    SUPPORTED_VISION_MIMES = {'image/png', 'image/jpeg', 'image/webp', 'image/gif'}

    def __init__(self, env):
        self.env = env

    def execute(self, run):
        profile = run.profile_id
        prompt = self._render_prompt(run)
        if profile.execution_mode == 'simulation':
            return self._simulate(run, prompt)
        provider = profile.llm_provider_id.sudo()
        if not provider:
            raise ValidationError(_('El agente no tiene proveedor configurado.'))
        if not provider.api_key:
            raise ValidationError(_('El proveedor no tiene API key configurada en LLM Connector.'))
        if profile.task_type in ('text', 'analysis'):
            return self._generate_text(provider, profile, run, prompt)
        return self._generate_image(provider, profile, run, prompt)

    def _render_prompt(self, run):
        profile = run.profile_id
        values = {
            'prompt': run.input_prompt or '',
            'brief': self._brief_context(run.brief_id),
            'hypothesis': self._hypothesis_context(run.creative_id.hypothesis_id),
            'creative': run.creative_id.name or '',
        }
        if not profile.prompt_template:
            rendered = values['prompt']
        else:
            try:
                rendered = profile.prompt_template.format(**values)
            except (KeyError, ValueError) as exc:
                raise ValidationError(_('La plantilla del agente contiene una variable inválida.')) from exc
        if profile.task_type in ('image', 'edit') and profile.system_prompt:
            return '%s\n\n%s' % (profile.system_prompt, rendered)
        return rendered

    def _brief_context(self, brief):
        if not brief:
            return ''
        return '\n'.join(filter(None, [
            'Marca: %s' % (brief.brand_name or ''),
            'Objetivo: %s' % (brief.objective or ''),
            'Oferta: %s' % (brief.offer or ''),
            'Público: %s' % (brief.target_audience or ''),
            'Dolores: %s' % (brief.pains or ''),
            'Deseos: %s' % (brief.desires or ''),
            'Objeciones: %s' % (brief.objections or ''),
            'Pruebas permitidas: %s' % (brief.proof or ''),
            'Acción esperada: %s' % (brief.expected_action or ''),
            'Guía de marca: %s' % (brief.brand_guidelines or ''),
            'Restricciones: %s' % (brief.constraints or ''),
        ]))

    def _hypothesis_context(self, hypothesis):
        if not hypothesis:
            return ''
        return '\n'.join(filter(None, [
            'Segmento: %s' % (hypothesis.segment or ''),
            'Dolor: %s' % (hypothesis.pain or ''),
            'Deseo: %s' % (hypothesis.desire or ''),
            'Ángulo: %s' % (hypothesis.angle or ''),
            'Hook: %s' % (hypothesis.hook or ''),
            'Conciencia: %s' % (hypothesis.awareness_level or ''),
            'Sofisticación: %s' % (hypothesis.sophistication_level or ''),
        ]))

    def _simulate(self, run, prompt):
        digest = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
        if run.profile_id.task_type in ('text', 'analysis'):
            payload = {
                'simulation': True,
                'summary': 'Resultado simulado para validar el workflow.',
                'prompt_fingerprint': digest[:12],
                'angles': [
                    {'name': 'Dolor inmediato', 'hypothesis': 'Priorizar el problema visible.'},
                    {'name': 'Resultado deseado', 'hypothesis': 'Mostrar la transformación.'},
                    {'name': 'Objeción principal', 'hypothesis': 'Reducir el riesgo percibido.'},
                ],
            }
            return {
                'text': json.dumps(payload, ensure_ascii=False, indent=2),
                'json': payload,
                'provider': 'simulation',
                'model': run.profile_id.model_alias or 'creative-simulator-v1',
                'request_id': 'sim-%s' % digest[:16],
            }
        svg = self._simulation_svg(run, prompt, digest)
        return {
            'file': base64.b64encode(svg.encode('utf-8')),
            'filename': 'creative-simulation-%s.svg' % digest[:8],
            'mime_type': 'image/svg+xml',
            'provider': 'simulation',
            'model': run.profile_id.model_alias or 'image-simulator-v1',
            'request_id': 'sim-%s' % digest[:16],
        }

    def _simulation_svg(self, run, prompt, digest):
        safe_title = escape((run.creative_id.name or 'Creative Lab')[:48])
        safe_prompt = escape(' '.join(prompt.split())[:120])
        accent = '#%s' % digest[:6]
        accent_two = '#%s' % digest[6:12]
        width, height = {
            '1:1': (1080, 1080),
            '4:5': (1080, 1350),
            '9:16': (1080, 1920),
            '1.91:1': (1200, 628),
        }.get(run.creative_id.aspect_ratio, (1080, 1080))
        margin = 80
        panel_width = width - (margin * 2)
        panel_height = height - (margin * 2)
        title_y = int(height * 0.33)
        prompt_y = int(height * 0.40)
        prompt_height = int(height * 0.28)
        footer_y = height - 150
        return '''<svg xmlns="http://www.w3.org/2000/svg"
  width="%(width)s" height="%(height)s" viewBox="0 0 %(width)s %(height)s">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="%(accent)s"/>
      <stop offset="1" stop-color="%(accent_two)s"/>
    </linearGradient>
  </defs>
  <rect width="%(width)s" height="%(height)s" fill="url(#g)"/>
  <rect x="%(margin)s" y="%(margin)s"
        width="%(panel_width)s" height="%(panel_height)s"
        rx="40" fill="#111827" fill-opacity=".76"/>
  <text x="130" y="190" fill="#F9FAFB" font-family="Arial, sans-serif" font-size="34">CREATIVE LAB · SIMULACIÓN</text>
  <text x="130" y="%(title_y)s" fill="#FFFFFF"
        font-family="Arial, sans-serif" font-size="72" font-weight="700">%(title)s</text>
  <foreignObject x="130" y="%(prompt_y)s" width="%(prompt_width)s" height="%(prompt_height)s">
    <div xmlns="http://www.w3.org/1999/xhtml"
         style="font: 36px Arial, sans-serif; color: #E5E7EB; line-height: 1.35;">%(prompt)s</div>
  </foreignObject>
  <text x="130" y="%(footer_y)s" fill="#D1D5DB"
        font-family="Arial, sans-serif" font-size="28">fingerprint %(digest)s</text>
</svg>''' % {
            'width': width,
            'height': height,
            'margin': margin,
            'panel_width': panel_width,
            'panel_height': panel_height,
            'title_y': title_y,
            'prompt_y': prompt_y,
            'prompt_width': width - 260,
            'prompt_height': prompt_height,
            'footer_y': footer_y,
            'accent': accent,
            'accent_two': accent_two,
            'title': safe_title,
            'prompt': safe_prompt,
            'digest': digest[:12],
        }

    def _generate_text(self, provider, profile, run, prompt):
        if profile.task_type == 'analysis' and (
            run.input_file or run.source_version_id.file
        ):
            return self._analyze_image(provider, profile, run, prompt)
        text = provider.generate(
            prompt,
            system=profile.system_prompt,
            model=profile.model_override or None,
            temperature=profile.temperature,
            max_tokens=profile.max_tokens,
        )
        return {
            'text': text,
            'provider': provider.name,
            'model': profile.model_override or provider.model,
        }

    def _analyze_image(self, provider, profile, run, prompt):
        mime_type = self._source_mime(run)
        if mime_type not in self.SUPPORTED_VISION_MIMES:
            raise UserError(_(
                'El análisis visual admite PNG, JPEG, WebP o GIF. '
                'Convertí el archivo antes de enviarlo al agente revisor.'
            ))
        encoded = run.input_file or run.source_version_id.file
        encoded_text = encoded.decode('ascii') if isinstance(encoded, bytes) else encoded
        if provider.provider_type == 'gemini':
            return self._analyze_gemini_image(
                provider, profile, prompt, mime_type, encoded_text
            )
        if provider.provider_type == 'anthropic':
            user_content = [
                {'type': 'text', 'text': prompt},
                {
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': mime_type,
                        'data': encoded_text,
                    },
                },
            ]
        elif provider.provider_type in self.VISION_OPENAI_COMPATIBLE:
            user_content = [
                {'type': 'text', 'text': prompt},
                {
                    'type': 'image_url',
                    'image_url': {
                        'url': 'data:%s;base64,%s' % (mime_type, encoded_text),
                    },
                },
            ]
        else:
            raise UserError(_(
                'El proveedor %s no expone análisis visual compatible.'
            ) % provider.name)
        messages = []
        if profile.system_prompt:
            messages.append({'role': 'system', 'content': profile.system_prompt})
        messages.append({'role': 'user', 'content': user_content})
        text = provider.chat_completion(
            messages,
            model=profile.model_override or None,
            temperature=profile.temperature,
            max_tokens=profile.max_tokens,
        )
        return {
            'text': text,
            'provider': provider.name,
            'model': profile.model_override or provider.model,
        }

    def _analyze_gemini_image(self, provider, profile, prompt, mime_type, encoded):
        base_url = (provider.base_url or 'https://generativelanguage.googleapis.com/v1beta').rstrip('/')
        model = profile.model_override or provider.model
        body = {
            'contents': [{
                'role': 'user',
                'parts': [
                    {'text': prompt},
                    {'inlineData': {'mimeType': mime_type, 'data': encoded}},
                ],
            }],
            'generationConfig': {
                'temperature': profile.temperature,
                'maxOutputTokens': profile.max_tokens,
            },
        }
        if profile.system_prompt:
            body['systemInstruction'] = {'parts': [{'text': profile.system_prompt}]}
        try:
            response = requests.post(
                '%s/models/%s:generateContent' % (base_url, model),
                headers={'Content-Type': 'application/json'},
                params={'key': provider.api_key.strip()},
                json=body,
                timeout=profile.timeout or provider.timeout or 120,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise UserError(self._http_error(provider, exc)) from exc
        parts = ((payload.get('candidates') or [{}])[0].get('content') or {}).get('parts', [])
        text = ''.join(part.get('text', '') for part in parts)
        if not text:
            raise UserError(_('Gemini no devolvió un análisis de la imagen.'))
        return {
            'text': text,
            'provider': provider.name,
            'model': model,
            'request_id': response.headers.get('x-request-id'),
        }

    def _generate_image(self, provider, profile, run, prompt):
        if provider.provider_type == 'gemini':
            return self._generate_gemini_image(provider, profile, run, prompt)
        if provider.provider_type in self.OPENAI_COMPATIBLE:
            return self._generate_openai_image(provider, profile, run, prompt)
        raise UserError(_(
            'El proveedor %s no expone generación de imágenes compatible. '
            'Usá simulación, carga manual o un proveedor OpenAI/Gemini.'
        ) % provider.name)

    def _generate_openai_image(self, provider, profile, run, prompt):
        base_url = (provider.base_url or 'https://api.openai.com/v1').rstrip('/')
        headers = {'Authorization': 'Bearer %s' % provider.api_key.strip()}
        model = profile.model_override or provider.model
        timeout = profile.timeout or provider.timeout or 120
        source = self._source_bytes(run)
        try:
            if source:
                response = requests.post(
                    base_url + '/images/edits',
                    headers=headers,
                    data={
                        'model': model,
                        'prompt': prompt,
                        'size': profile.image_size,
                        'response_format': 'b64_json',
                    },
                    files={'image': (self._source_filename(run), source, self._source_mime(run))},
                    timeout=timeout,
                )
            else:
                response = requests.post(
                    base_url + '/images/generations',
                    headers={**headers, 'Content-Type': 'application/json'},
                    json={
                        'model': model,
                        'prompt': prompt,
                        'size': profile.image_size,
                        'response_format': 'b64_json',
                    },
                    timeout=timeout,
                )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise UserError(self._http_error(provider, exc)) from exc
        item = (payload.get('data') or [{}])[0]
        encoded = item.get('b64_json')
        if not encoded and item.get('url'):
            try:
                download = requests.get(item['url'], timeout=timeout)
                download.raise_for_status()
                encoded = base64.b64encode(download.content).decode('ascii')
            except requests.RequestException as exc:
                raise UserError(_('La imagen se generó pero no pudo descargarse.')) from exc
        if not encoded:
            raise UserError(_('El proveedor no devolvió una imagen.'))
        return {
            'file': encoded,
            'filename': 'generated-%s.png' % (run.idempotency_key[:8]),
            'mime_type': 'image/png',
            'provider': provider.name,
            'model': model,
            'request_id': response.headers.get('x-request-id'),
        }

    def _generate_gemini_image(self, provider, profile, run, prompt):
        base_url = (provider.base_url or 'https://generativelanguage.googleapis.com/v1beta').rstrip('/')
        model = profile.model_override or provider.model
        parts = [{'text': prompt}]
        source = self._source_bytes(run)
        if source:
            parts.append({
                'inlineData': {
                    'mimeType': self._source_mime(run),
                    'data': base64.b64encode(source).decode('ascii'),
                },
            })
        body = {
            'contents': [{'role': 'user', 'parts': parts}],
            'generationConfig': {'responseModalities': ['TEXT', 'IMAGE']},
        }
        try:
            response = requests.post(
                '%s/models/%s:generateContent' % (base_url, model),
                headers={'Content-Type': 'application/json'},
                params={'key': provider.api_key.strip()},
                json=body,
                timeout=profile.timeout or provider.timeout or 120,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise UserError(self._http_error(provider, exc)) from exc
        response_parts = ((payload.get('candidates') or [{}])[0].get('content') or {}).get('parts', [])
        inline = next((part.get('inlineData') for part in response_parts if part.get('inlineData')), None)
        if not inline or not inline.get('data'):
            raise UserError(_('Gemini no devolvió una imagen. Verificá que el modelo admita salida IMAGE.'))
        mime = inline.get('mimeType') or 'image/png'
        extension = 'jpg' if mime == 'image/jpeg' else 'png'
        return {
            'file': inline['data'],
            'filename': 'generated-%s.%s' % (run.idempotency_key[:8], extension),
            'mime_type': mime,
            'provider': provider.name,
            'model': model,
        }

    def _source_bytes(self, run):
        encoded = run.input_file or run.source_version_id.file
        return base64.b64decode(encoded) if encoded else None

    def _source_filename(self, run):
        return run.input_filename or run.source_version_id.filename or 'source.png'

    def _source_mime(self, run):
        return run.input_mime_type or run.source_version_id.mime_type or 'image/png'

    def _http_error(self, provider, error):
        detail = ''
        if error.response is not None:
            detail = error.response.text[:800]
        message = _('Error al generar con %(provider)s: %(detail)s') % {
            'provider': provider.name,
            'detail': detail or str(error),
        }
        if provider.api_key:
            message = message.replace(provider.api_key, '***')
        return message
