# -*- coding: utf-8 -*-

import base64
import hashlib
import io
import json
import mimetypes
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow forma parte del runtime normal de Odoo
    Image = None


class CreativeAsset(models.Model):
    _name = 'creative.asset'
    _description = 'Creativo'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'creative.lab.mixin']
    _order = 'id desc'
    _check_company_auto = True

    name = fields.Char(string='Nombre', required=True, tracking=True)
    active = fields.Boolean(default=True)
    brief_id = fields.Many2one(
        'creative.brief',
        string='Brief',
        required=True,
        check_company=True,
        ondelete='cascade',
        tracking=True,
        index=True,
    )
    company_id = fields.Many2one(
        related='brief_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    project_id = fields.Many2one(
        related='brief_id.project_id',
        store=True,
        readonly=True,
        index=True,
    )
    hypothesis_id = fields.Many2one(
        'creative.hypothesis',
        string='Hipótesis',
        check_company=True,
        tracking=True,
        ondelete='set null',
    )
    owner_id = fields.Many2one(
        'res.users',
        string='Responsable',
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
    )
    state = fields.Selection(
        [
            ('draft', 'Borrador'),
            ('generating', 'Generando'),
            ('review', 'En revisión'),
            ('approved', 'Aprobado'),
            ('rejected', 'Rechazado'),
            ('archived', 'Archivado'),
        ],
        default='draft',
        required=True,
        tracking=True,
        index=True,
    )
    asset_type = fields.Selection(
        [('image', 'Imagen'), ('carousel', 'Carrusel'), ('video', 'Video')],
        string='Tipo',
        default='image',
        required=True,
    )
    aspect_ratio = fields.Selection(
        [
            ('1:1', '1:1 · Cuadrado'),
            ('4:5', '4:5 · Feed'),
            ('9:16', '9:16 · Stories/Reels'),
            ('1.91:1', '1.91:1 · Horizontal'),
        ],
        default='1:1',
        required=True,
    )
    placement = fields.Selection(
        [
            ('feed', 'Feed'),
            ('story', 'Stories'),
            ('reel', 'Reels'),
            ('status', 'Estado de WhatsApp'),
            ('multi', 'Múltiples ubicaciones'),
        ],
        default='feed',
        required=True,
    )
    headline = fields.Char(string='Titular')
    primary_text = fields.Text(string='Texto principal')
    call_to_action = fields.Char(string='Llamado a la acción', default='Enviar mensaje')
    notes = fields.Html(string='Notas')

    version_ids = fields.One2many('creative.asset.version', 'creative_id', string='Versiones')
    current_version_id = fields.Many2one(
        'creative.asset.version',
        string='Versión actual',
        copy=False,
        check_company=True,
        ondelete='restrict',
        tracking=True,
    )
    preview_file = fields.Binary(
        related='current_version_id.file',
        string='Vista previa',
        readonly=True,
    )
    preview_filename = fields.Char(
        related='current_version_id.filename',
        readonly=True,
    )
    version_count = fields.Integer(compute='_compute_counts')
    publication_count = fields.Integer(compute='_compute_counts')
    outcome_count = fields.Integer(compute='_compute_counts')
    publication_ids = fields.One2many('creative.publication', 'creative_id', string='Publicaciones')

    approved_by_id = fields.Many2one('res.users', string='Aprobado por', readonly=True, copy=False)
    approved_at = fields.Datetime(string='Aprobado el', readonly=True, copy=False)
    rejection_reason = fields.Text(string='Motivo de rechazo', copy=False)
    next_step_hint = fields.Char(compute='_compute_next_step_hint', compute_sudo=True)

    @api.depends('version_ids', 'publication_ids', 'publication_ids.outcome_ids')
    def _compute_counts(self):
        for creative in self:
            creative.version_count = len(creative.version_ids)
            creative.publication_count = len(creative.publication_ids)
            creative.outcome_count = sum(len(publication.outcome_ids) for publication in creative.publication_ids)

    @api.depends('state', 'version_ids', 'current_version_id')
    def _compute_next_step_hint(self):
        for creative in self:
            hint = False
            current = creative.current_version_id
            if creative.state == 'archived':
                hint = False
            elif not creative.version_ids:
                hint = _('Generá la primera versión con el botón Generar / retocar.')
            elif current and current.export_ids:
                hint = _('Creá una publicación en Meta o descargá el archivo.')
            elif current and current.state == 'approved':
                hint = _('Exportá la versión limpia para usarla o publicarla.')
            elif current and current.state == 'review':
                hint = _('Esperando aprobación.')
            elif current and current.state in ('draft', 'rejected'):
                if creative.simple_mode:
                    hint = _('Generá una nueva versión para aprobarla automáticamente.')
                else:
                    hint = _('Enviá la versión a revisión.')
            creative.next_step_hint = hint

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if (
                vals.get('state', 'draft') != 'draft'
                or vals.get('current_version_id')
                or vals.get('approved_by_id')
                or vals.get('approved_at')
            ):
                raise AccessError(_('Los creativos deben iniciar como borrador.'))
        return super().create(vals_list)

    def write(self, vals):
        protected = {'state', 'current_version_id', 'approved_by_id', 'approved_at'}
        if protected.intersection(vals):
            raise AccessError(_('Usá las acciones de Creative Lab para cambiar aprobación o versión actual.'))
        return super().write(vals)

    def _system_write(self, vals):
        return super(CreativeAsset, self).write(vals)

    @api.constrains('brief_id', 'hypothesis_id')
    def _check_hypothesis_brief(self):
        for creative in self:
            if creative.hypothesis_id and creative.hypothesis_id.brief_id != creative.brief_id:
                raise ValidationError(_('La hipótesis y el creativo deben pertenecer al mismo brief.'))

    @api.constrains('current_version_id')
    def _check_current_version(self):
        for creative in self:
            if creative.current_version_id and creative.current_version_id.creative_id != creative:
                raise ValidationError(_('La versión actual debe pertenecer al creativo.'))

    def copy(self, default=None):
        values = dict(default or {})
        values.setdefault('name', _('%s (copia)') % self.name)
        values.update({
            'current_version_id': False,
            'state': 'draft',
            'approved_by_id': False,
            'approved_at': False,
            'rejection_reason': False,
        })
        return super().copy(values)

    def action_open_generate_wizard(self):
        self.ensure_one()
        domain = [
            ('company_id', '=', self.company_id.id),
            ('task_type', 'in', ('image', 'edit')),
            ('active', '=', True),
        ]
        profile = self.env['creative.agent.profile'].search(domain, limit=1)
        if profile and self._simple_mode_enabled() and profile.execution_mode == 'simulation':
            real_profile = self.env['creative.agent.profile'].search(
                domain + [('execution_mode', '!=', 'simulation')],
                limit=1,
            )
            profile = real_profile or profile
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generar o retocar creativo'),
            'res_model': 'creative.generate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_creative_id': self.id,
                'default_source_version_id': self.current_version_id.id,
                'default_agent_profile_id': profile.id,
                'default_operation': 'edit' if self.current_version_id else 'initial',
            },
        }

    def action_suggest_copy(self):
        self.ensure_one()
        targets = [
            field
            for field in ('headline', 'primary_text', 'call_to_action')
            if not self[field] or self[field] == 'Enviar mensaje'
        ]
        if not targets:
            raise ValidationError(_(
                'El copy ya está completo. Borrá el campo que quieras regenerar.'
            ))
        suggestions = self._suggest_json(
            _('Redactá el copy del anuncio. Respondé exclusivamente con JSON '
              'válido con esta forma: '
              '{"headline": "...", "primary_text": "...", "call_to_action": "..."}. '
              'headline: una sola línea, máximo 40 caracteres, directo. '
              'primary_text: 1 o 2 oraciones, máximo 125 caracteres, tono cercano. '
              'call_to_action: 2 a 4 palabras para el botón. '
              'Sin comillas extra ni explicaciones.'),
            targets,
            kind='copy',
        )
        for field in targets:
            if suggestions.get(field):
                self[field] = suggestions[field]

    _SUGGESTION_KEY_ALIASES = {
        'prompt': ('prompt', 'image_prompt'),
        'negative_prompt': ('negative_prompt', 'avoid'),
        'headline': ('headline',),
        'primary_text': ('primary_text', 'message'),
        'call_to_action': ('call_to_action', 'cta'),
        'description': ('description',),
    }

    def _suggest_json(self, goal, keys, kind=None):
        if kind:
            style = self._suggestion_style(kind)
            if style:
                goal = '%s\n\n%s\n%s' % (
                    goal,
                    _('Indicaciones globales de estilo:'),
                    style,
                )
        text = self._suggest_text(goal, False)
        try:
            payload = self.env['creative.agent.run']._parse_json(text)
        except ValidationError:
            match = re.search(r'\{.*\}', text, flags=re.DOTALL)
            if not match:
                raise
            try:
                payload = json.loads(match.group(0))
            except ValueError:
                raise ValidationError(_('El agente no devolvió JSON válido.'))
        if not isinstance(payload, dict):
            raise ValidationError(_('El agente no devolvió un objeto JSON.'))
        suggestions = {}
        for key in keys:
            value = self._find_suggestion_value(payload, key)
            if value:
                suggestions[key] = value
        if not suggestions:
            raise ValidationError(_(
                'El agente no devolvió los campos esperados. Reintentá.'
            ))
        return suggestions

    def _find_suggestion_value(self, payload, key, depth=0):
        """Find a field by alias anywhere in the agent's (possibly nested) JSON.

        Agents configured with their own templates may wrap the answer in their
        usual shape (e.g. ``{"concepts": [{...}] }``); the copy we need lives
        inside, so we search recursively.
        """
        if depth > 4:
            return False
        if isinstance(payload, dict):
            for alias in self._SUGGESTION_KEY_ALIASES.get(key, (key,)):
                value = payload.get(alias)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            for child in payload.values():
                found = self._find_suggestion_value(child, key, depth + 1)
                if found:
                    return found
        elif isinstance(payload, list):
            for child in payload:
                found = self._find_suggestion_value(child, key, depth + 1)
                if found:
                    return found
        return False

    def _suggest_text(self, goal, draft):
        self.ensure_one()
        profile = self._get_text_suggestion_profile()
        instruction = goal
        if draft:
            instruction = '%s\n\n%s:\n%s' % (
                instruction,
                _('Mejorá y completá este borrador del usuario'),
                draft,
            )
        summary = self._ai_context()
        if summary:
            instruction = '%s\n\n%s:\n%s' % (instruction, _('Contexto'), summary)
        run = self.env['creative.agent.run'].create({
            'profile_id': profile.id,
            'company_id': self.company_id.id,
            'brief_id': self.brief_id.id,
            'creative_id': self.id,
            'operation': 'strategy',
            'input_prompt': instruction,
        })
        run._execute()
        if run.status != 'succeeded' or not run.output_text:
            raise ValidationError(
                _('La sugerencia falló: %s')
                % (run.error_message or _('el agente no devolvió texto.'))
            )
        return run.output_text.strip()

    def _get_text_suggestion_profile(self):
        profiles = self.env['creative.agent.profile'].search([
            ('company_id', '=', self.company_id.id),
            ('active', '=', True),
            ('task_type', '=', 'text'),
        ])
        if not profiles:
            raise ValidationError(_(
                'No hay ningún agente de texto configurado. Crealo en '
                'Creative Lab > Configuración > Agentes con tipo de tarea Texto.'
            ))
        real_profiles = profiles.filtered(lambda item: item.execution_mode != 'simulation')
        candidates = real_profiles or profiles
        director = candidates.filtered(lambda item: item.role == 'creative_director')
        return (director or candidates)[0]

    def _ai_context(self):
        brief = self.brief_id
        hypothesis = self.hypothesis_id
        lines = []
        for label, value in (
            (_('Objetivo'), brief.objective),
            (_('Oferta'), brief.offer),
            (_('Público'), brief.target_audience),
            (_('Ángulo de la hipótesis'), hypothesis.angle),
            (_('Hook de la hipótesis'), hypothesis.hook),
            (_('Titular del creativo'), self.headline),
            (_('Texto principal del creativo'), self.primary_text),
        ):
            if value:
                lines.append('%s: %s' % (label, value))
        if self.aspect_ratio or self.placement:
            lines.append('%s: %s / %s' % (
                _('Formato'),
                self.aspect_ratio or '-',
                self.placement or '-',
            ))
        return '\n'.join(lines)

    def action_submit_review(self):
        for creative in self:
            if not creative.current_version_id:
                raise ValidationError(_('Generá o importá una versión antes de enviarla a revisión.'))
            creative.current_version_id.action_submit_review()
            creative._system_write({'state': 'review'})

    def action_approve(self):
        self._check_approval_access()
        for creative in self:
            if not creative.current_version_id:
                raise ValidationError(_('No hay una versión actual para aprobar.'))
            creative.current_version_id.action_approve()

    def action_reject(self):
        self._check_approval_access()
        for creative in self:
            if not creative.rejection_reason:
                raise ValidationError(_('Indicá el motivo de rechazo.'))
            if not creative.current_version_id:
                raise ValidationError(_('No hay una versión actual para rechazar.'))
            creative.current_version_id.write({
                'rejection_reason': creative.rejection_reason,
            })
            creative.current_version_id.action_reject()
            creative._system_write({'state': 'rejected'})

    def action_reset_draft(self):
        self._system_write({
            'state': 'draft',
            'approved_by_id': False,
            'approved_at': False,
        })

    def action_archive(self):
        self._system_write({'state': 'archived', 'active': False})

    def _check_approval_access(self):
        if not self.env.user.has_group('creative_lab.grupo_creative_aprobador'):
            raise AccessError(_('Solo un aprobador de Creative Lab puede realizar esta acción.'))

    def action_view_versions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Versiones — %s') % self.display_name,
            'res_model': 'creative.asset.version',
            'view_mode': 'list,form',
            'domain': [('creative_id', '=', self.id)],
            'context': {'default_creative_id': self.id},
        }

    def action_view_publications(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Publicaciones — %s') % self.display_name,
            'res_model': 'creative.publication',
            'view_mode': 'list,form',
            'domain': [('creative_id', '=', self.id)],
            'context': {
                'default_creative_id': self.id,
                'default_version_id': self.current_version_id.id,
            },
        }

    def action_open_agent_wizard(self):
        self.ensure_one()
        profile = self.env['creative.agent.profile'].search([
            ('company_id', '=', self.company_id.id),
            ('role', '=', 'reviewer'),
            ('task_type', '=', 'analysis'),
            ('active', '=', True),
        ], limit=1)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ejecutar agente sobre el creativo'),
            'res_model': 'creative.agent.run.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_brief_id': self.brief_id.id,
                'default_creative_id': self.id,
                'default_source_version_id': self.current_version_id.id,
                'default_profile_id': profile.id,
                'default_operation': 'review',
            },
        }


class CreativeAssetVersion(models.Model):
    _name = 'creative.asset.version'
    _description = 'Versión de activo creativo'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'creative.lab.mixin']
    _order = 'creative_id, revision desc, id desc'
    _check_company_auto = True

    _unique_revision = models.Constraint(
        'UNIQUE(creative_id, revision)',
        'El número de revisión debe ser único dentro de cada creativo.',
    )

    name = fields.Char(string='Código', required=True, readonly=True, copy=False)
    active = fields.Boolean(default=True)
    creative_id = fields.Many2one(
        'creative.asset',
        string='Creativo',
        required=True,
        ondelete='cascade',
        check_company=True,
        index=True,
    )
    company_id = fields.Many2one(
        related='creative_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    revision = fields.Integer(string='Revisión', required=True, readonly=True, copy=False)
    parent_id = fields.Many2one(
        'creative.asset.version',
        string='Versión padre',
        ondelete='restrict',
        check_company=True,
        readonly=True,
        copy=False,
        index=True,
    )
    child_ids = fields.One2many('creative.asset.version', 'parent_id', string='Ramas')
    operation = fields.Selection(
        [
            ('initial', 'Generación inicial'),
            ('import', 'Archivo importado'),
            ('edit', 'Retoque'),
            ('variation', 'Variación'),
        ],
        required=True,
        default='initial',
        readonly=True,
    )
    state = fields.Selection(
        [
            ('draft', 'Borrador'),
            ('review', 'En revisión'),
            ('approved', 'Aprobada'),
            ('rejected', 'Rechazada'),
        ],
        default='draft',
        required=True,
        tracking=True,
        index=True,
    )
    prompt = fields.Text(string='Prompt', readonly=True)
    negative_prompt = fields.Text(string='Prompt negativo', readonly=True)
    source_filename = fields.Char(string='Archivo fuente', readonly=True)
    source_sha256 = fields.Char(string='Hash de fuente', readonly=True, copy=False)
    file = fields.Binary(string='Archivo', required=True, attachment=True, readonly=True, copy=False)
    filename = fields.Char(string='Nombre del archivo', required=True, readonly=True)
    mime_type = fields.Char(string='Tipo MIME', readonly=True)
    file_size = fields.Integer(string='Tamaño', readonly=True)
    width = fields.Integer(string='Ancho', readonly=True)
    height = fields.Integer(string='Alto', readonly=True)
    sha256 = fields.Char(string='SHA-256', required=True, readonly=True, copy=False, index=True)
    agent_profile_id = fields.Many2one(
        'creative.agent.profile',
        string='Agente',
        readonly=True,
        ondelete='restrict',
    )
    agent_run_id = fields.Many2one(
        'creative.agent.run',
        string='Ejecución',
        readonly=True,
        copy=False,
        ondelete='restrict',
    )
    provider_snapshot = fields.Char(string='Proveedor', readonly=True)
    model_snapshot = fields.Char(string='Modelo', readonly=True)
    parameters_json = fields.Json(string='Parámetros', readonly=True)
    external_request_id = fields.Char(string='Request ID', readonly=True, copy=False)
    estimated_cost = fields.Float(string='Costo estimado USD', digits=(12, 6), readonly=True)
    author_id = fields.Many2one(
        'res.users',
        string='Autor',
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
    )
    approval_requested_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    approval_requested_at = fields.Datetime(readonly=True, copy=False)
    approved_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    rejection_reason = fields.Text(string='Motivo de rechazo', copy=False)
    notes = fields.Text(string='Notas de revisión')
    export_ids = fields.One2many('creative.asset.export', 'version_id', string='Exportaciones')
    export_count = fields.Integer(compute='_compute_export_count')

    _immutable_payload_fields = {
        'creative_id', 'revision', 'parent_id', 'operation', 'prompt',
        'negative_prompt', 'source_filename', 'source_sha256', 'file',
        'filename', 'mime_type', 'file_size', 'width', 'height', 'sha256',
        'agent_profile_id', 'agent_run_id', 'provider_snapshot',
        'model_snapshot', 'parameters_json', 'external_request_id',
        'estimated_cost', 'author_id',
    }

    @api.depends('export_ids')
    def _compute_export_count(self):
        for version in self:
            version.export_count = len(version.export_ids)

    @api.model_create_multi
    def create(self, vals_list):
        prepared = []
        for incoming in vals_list:
            vals = dict(incoming)
            if (
                vals.get('state', 'draft') != 'draft'
                or vals.get('approval_requested_by_id')
                or vals.get('approval_requested_at')
                or vals.get('approved_by_id')
                or vals.get('approved_at')
            ):
                raise AccessError(_('Las versiones deben iniciar como borrador.'))
            creative = self.env['creative.asset'].browse(vals['creative_id']).exists()
            if not creative:
                raise ValidationError(_('El creativo indicado no existe.'))
            if vals.get('parent_id'):
                parent = self.browse(vals['parent_id']).exists()
                if not parent or parent.creative_id != creative:
                    raise ValidationError(_('La versión padre debe pertenecer al mismo creativo.'))
            if not vals.get('revision'):
                last = self.search(
                    [('creative_id', '=', creative.id)],
                    order='revision desc',
                    limit=1,
                )
                vals['revision'] = (last.revision if last else 0) + 1
            vals.setdefault('name', '%s · v%s' % (creative.name, vals['revision']))
            self._prepare_binary_metadata(vals)
            prepared.append(vals)
        records = super().create(prepared)
        if self._simple_mode_enabled():
            for version in records:
                version._system_write({
                    'state': 'approved',
                    'approved_by_id': self.env.user.id,
                    'approved_at': fields.Datetime.now(),
                    'rejection_reason': False,
                })
        for version in records:
            values = {
                'current_version_id': version.id,
                'state': 'approved' if version.state == 'approved' else 'generating',
            }
            if version.state == 'approved':
                values.update({
                    'approved_by_id': version.approved_by_id.id,
                    'approved_at': version.approved_at,
                    'rejection_reason': False,
                })
            version.creative_id._system_write(values)
        return records

    def write(self, vals):
        changed_payload = self._immutable_payload_fields.intersection(vals)
        if changed_payload:
            raise UserError(
                _('Las versiones son inmutables. Creá una rama nueva para cambiar: %s.')
                % ', '.join(sorted(changed_payload))
            )
        workflow_fields = {
            'state', 'approval_requested_by_id', 'approval_requested_at',
            'approved_by_id', 'approved_at',
        }
        if workflow_fields.intersection(vals):
            raise UserError(_('Usá las acciones de revisión, aprobación o rechazo para cambiar la auditoría.'))
        return super().write(vals)

    def _system_write(self, vals):
        return super(CreativeAssetVersion, self).write(vals)

    def unlink(self):
        raise UserError(_('Las versiones no se eliminan porque forman parte de la trazabilidad. Archivalas.'))

    @api.constrains('parent_id', 'creative_id')
    def _check_parent_lineage(self):
        for version in self:
            current = version.parent_id
            seen = {version.id}
            while current:
                if current.id in seen:
                    raise ValidationError(_('El linaje de versiones no puede contener ciclos.'))
                if current.creative_id != version.creative_id:
                    raise ValidationError(_('Todo el linaje debe pertenecer al mismo creativo.'))
                seen.add(current.id)
                current = current.parent_id

    @api.model
    def _prepare_binary_metadata(self, vals):
        encoded = vals.get('file')
        if not encoded:
            raise ValidationError(_('La versión necesita un archivo materializado.'))
        try:
            raw = base64.b64decode(encoded)
        except Exception as exc:
            raise ValidationError(_('El archivo no contiene base64 válido.')) from exc
        if not raw:
            raise ValidationError(_('El archivo está vacío.'))
        filename = vals.get('filename') or 'creative.bin'
        vals['sha256'] = hashlib.sha256(raw).hexdigest()
        vals['file_size'] = len(raw)
        vals['mime_type'] = vals.get('mime_type') or self._guess_mime(filename, raw)
        width, height = self._image_dimensions(raw)
        if vals['mime_type'] == 'image/svg+xml':
            if vals.get('provider_snapshot') != 'simulation':
                raise ValidationError(_(
                    'Por seguridad, SVG solo se admite como salida del simulador local.'
                ))
        elif vals['mime_type'] in ('image/png', 'image/jpeg', 'image/webp', 'image/gif'):
            if not width or not height:
                raise ValidationError(_('El archivo no es una imagen válida.'))
        else:
            raise ValidationError(_('El activo debe ser PNG, JPEG, WebP, GIF o una simulación SVG.'))
        vals['width'] = width
        vals['height'] = height

    @api.model
    def _guess_mime(self, filename, raw):
        if raw.lstrip().startswith(b'<svg') or b'<svg' in raw[:500]:
            return 'image/svg+xml'
        guessed = mimetypes.guess_type(filename)[0]
        return guessed or 'application/octet-stream'

    @api.model
    def _image_dimensions(self, raw):
        if raw.lstrip().startswith(b'<svg'):
            header = raw[:2048]
            width_match = re.search(rb'\bwidth=["\'](\d+)["\']', header)
            height_match = re.search(rb'\bheight=["\'](\d+)["\']', header)
            if width_match and height_match:
                return int(width_match.group(1)), int(height_match.group(1))
        if not Image:
            return 0, 0
        try:
            with Image.open(io.BytesIO(raw)) as image:
                return image.size
        except Exception:
            return 0, 0

    def action_submit_review(self):
        for version in self:
            if version.state not in ('draft', 'rejected'):
                raise ValidationError(_('Solo una versión borrador o rechazada puede enviarse a revisión.'))
            version._system_write({
                'state': 'review',
                'approval_requested_by_id': self.env.user.id,
                'approval_requested_at': fields.Datetime.now(),
                'rejection_reason': False,
            })

    def action_approve(self):
        if not self.env.user.has_group('creative_lab.grupo_creative_aprobador'):
            raise AccessError(_('Solo un aprobador puede aprobar versiones.'))
        for version in self:
            if version.state != 'review':
                raise ValidationError(_('La versión debe estar en revisión.'))
            if (
                version.author_id == self.env.user
                and not self.env.user.has_group('creative_lab.grupo_creative_administrador')
            ):
                raise AccessError(_('La persona que creó la versión no puede aprobarla.'))
            version._system_write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approved_at': fields.Datetime.now(),
                'rejection_reason': False,
            })
            version.creative_id._system_write({
                'current_version_id': version.id,
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approved_at': fields.Datetime.now(),
                'rejection_reason': False,
            })

    def action_reject(self):
        if not self.env.user.has_group('creative_lab.grupo_creative_aprobador'):
            raise AccessError(_('Solo un aprobador puede rechazar versiones.'))
        for version in self:
            if version.state != 'review':
                raise ValidationError(_('La versión debe estar en revisión.'))
            if not version.rejection_reason:
                raise ValidationError(_('Indicá el motivo de rechazo en las notas de la versión.'))
            version._system_write({'state': 'rejected'})

    def action_open_branch_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Crear rama desde %s') % self.name,
            'res_model': 'creative.generate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_creative_id': self.creative_id.id,
                'default_source_version_id': self.id,
                'default_operation': 'edit',
            },
        }

    def action_open_export_wizard(self):
        self.ensure_one()
        if self.state != 'approved':
            raise ValidationError(_('Solo se pueden exportar versiones aprobadas.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Exportar versión aprobada'),
            'res_model': 'creative.asset.export.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_version_id': self.id},
        }

    def action_open_review_agent_wizard(self):
        self.ensure_one()
        profile = self.env['creative.agent.profile'].search([
            ('company_id', '=', self.company_id.id),
            ('role', '=', 'reviewer'),
            ('task_type', '=', 'analysis'),
            ('active', '=', True),
        ], limit=1)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Revisar versión con IA'),
            'res_model': 'creative.agent.run.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_brief_id': self.creative_id.brief_id.id,
                'default_creative_id': self.creative_id.id,
                'default_source_version_id': self.id,
                'default_profile_id': profile.id,
                'default_operation': 'review',
            },
        }

    def action_view_exports(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Exportaciones — %s') % self.name,
            'res_model': 'creative.asset.export',
            'view_mode': 'list,form',
            'domain': [('version_id', '=', self.id)],
            'context': {'default_version_id': self.id},
        }
