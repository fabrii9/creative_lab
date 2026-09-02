# -*- coding: utf-8 -*-

import base64
import hashlib
import io
import os
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover
    Image = None
    ImageOps = None


class CreativeAssetExportWizard(models.TransientModel):
    _name = 'creative.asset.export.wizard'
    _description = 'Exportar y limpiar un activo creativo'

    version_id = fields.Many2one('creative.asset.version', required=True, readonly=True)
    output_format = fields.Selection(
        [('original', 'Conservar formato'), ('png', 'PNG'), ('jpeg', 'JPEG'), ('webp', 'WebP')],
        required=True,
        default='original',
    )
    quality = fields.Integer(default=92)
    strip_metadata = fields.Boolean(
        string='Eliminar metadatos sensibles',
        default=True,
        help='Elimina EXIF/XMP y conserva el perfil ICC cuando está disponible.',
    )

    @api.constrains('quality')
    def _check_quality(self):
        for wizard in self:
            if not 1 <= wizard.quality <= 100:
                raise ValidationError(_('La calidad debe estar entre 1 y 100.'))

    def action_export(self):
        self.ensure_one()
        if self.version_id.state != 'approved':
            raise ValidationError(_('Solo se pueden exportar versiones aprobadas.'))
        fingerprint = hashlib.sha256(
            ('%s|%s|%s|%s' % (
                self.version_id.id,
                self.output_format,
                self.quality,
                int(self.strip_metadata),
            )).encode('utf-8')
        ).hexdigest()
        existing = self.env['creative.asset.export'].search(
            [('fingerprint', '=', fingerprint)],
            limit=1,
        )
        if existing:
            export = existing
        else:
            raw = base64.b64decode(self.version_id.file)
            output, extension, mime = self._process(raw)
            safe_base = re.sub(r'[^a-zA-Z0-9_-]+', '-', os.path.splitext(self.version_id.filename)[0]).strip('-')
            filename = '%s-clean.%s' % (safe_base or 'creative', extension)
            export = self.env['creative.asset.export'].create({
                'name': _('Export %s') % self.version_id.name,
                'version_id': self.version_id.id,
                'file': base64.b64encode(output),
                'filename': filename,
                'mime_type': mime,
                'output_format': self.output_format,
                'quality': self.quality,
                'metadata_removed': self.strip_metadata,
                'fingerprint': fingerprint,
            })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Exportación lista'),
            'res_model': 'creative.asset.export',
            'res_id': export.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _process(self, raw):
        source_mime = self.version_id.mime_type or ''
        if source_mime == 'image/svg+xml':
            if self.output_format != 'original':
                raise UserError(_('El simulador produce SVG. Exportalo en formato original o usá una imagen raster.'))
            cleaned = self._clean_svg(raw) if self.strip_metadata else raw
            return cleaned, 'svg', 'image/svg+xml'
        if self.output_format == 'original' and not self.strip_metadata:
            extension = os.path.splitext(self.version_id.filename)[1].lstrip('.') or 'bin'
            return raw, extension, source_mime or 'application/octet-stream'
        if not Image or not ImageOps:
            raise UserError(_('Pillow no está disponible para limpiar o convertir la imagen.'))
        try:
            with Image.open(io.BytesIO(raw)) as source:
                image = ImageOps.exif_transpose(source)
                original_format = (source.format or 'PNG').upper()
                icc_profile = source.info.get('icc_profile')
                target_format = {
                    'original': original_format,
                    'png': 'PNG',
                    'jpeg': 'JPEG',
                    'webp': 'WEBP',
                }[self.output_format]
                if target_format == 'JPEG' and image.mode not in ('RGB', 'L'):
                    background = Image.new('RGB', image.size, (255, 255, 255))
                    if image.mode == 'RGBA':
                        background.paste(image, mask=image.getchannel('A'))
                    else:
                        background.paste(image.convert('RGB'))
                    image = background
                output = io.BytesIO()
                save_kwargs = {}
                if target_format in ('JPEG', 'WEBP'):
                    save_kwargs['quality'] = self.quality
                    save_kwargs['optimize'] = True
                if icc_profile:
                    save_kwargs['icc_profile'] = icc_profile
                image.save(output, format=target_format, **save_kwargs)
        except Exception as exc:
            raise UserError(_('No se pudo procesar la imagen: %s') % str(exc)[:500]) from exc
        extension, mime = {
            'PNG': ('png', 'image/png'),
            'JPEG': ('jpg', 'image/jpeg'),
            'WEBP': ('webp', 'image/webp'),
        }.get(target_format, (target_format.lower(), source_mime or 'application/octet-stream'))
        return output.getvalue(), extension, mime

    def _clean_svg(self, raw):
        text = raw.decode('utf-8', errors='strict')
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
        text = re.sub(r'<metadata\b[^>]*>.*?</metadata>', '', text, flags=re.DOTALL | re.IGNORECASE)
        return text.encode('utf-8')
