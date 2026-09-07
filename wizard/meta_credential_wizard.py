# -*- coding: utf-8 -*-

from odoo import _, fields, models
from odoo.exceptions import ValidationError


class CreativeMetaCredentialWizard(models.TransientModel):
    _name = 'creative.meta.credential.wizard'
    _description = 'Guardar credenciales de Meta Ads'
    _check_company_auto = True

    meta_account_id = fields.Many2one(
        'creative.meta.account', string='Conexión Meta', required=True, readonly=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        related='meta_account_id.company_id', readonly=True,
    )
    access_token = fields.Char(
        string='Access Token', required=True, copy=False, exportable=False,
    )
    app_secret = fields.Char(
        string='App Secret', copy=False, exportable=False,
        help='Dejalo vacío para conservar el App Secret ya guardado.',
    )
    clear_app_secret = fields.Boolean(
        string='Eliminar el App Secret guardado',
        help='Marcá esta opción si querés usar el token sin appsecret_proof.',
    )

    def action_save_credentials(self):
        self.ensure_one()
        account = self.meta_account_id.exists()
        if not account:
            raise ValidationError(_('La conexión Meta ya no existe.'))
        clear_app_secret = bool(self.clear_app_secret and not self.app_secret)
        replace_app_secret = bool(self.app_secret or clear_app_secret)
        account._set_stored_credentials(
            self.access_token,
            app_secret=False if clear_app_secret else self.app_secret,
            replace_app_secret=replace_app_secret,
        )
        account_id = account.id
        self.unlink()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Conexión Meta Ads'),
            'res_model': 'creative.meta.account',
            'res_id': account_id,
            'view_mode': 'form',
            'target': 'current',
        }
