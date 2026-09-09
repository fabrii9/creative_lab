# -*- coding: utf-8 -*-

import logging

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class WhatsappAccount(models.Model):
    _inherit = 'whatsapp.account'

    def _process_messages(self, value):
        result = super()._process_messages(value)
        self._creative_lab_capture_referrals(value)
        return result

    def _creative_lab_capture_referrals(self, value):
        """Persist Meta click-to-WhatsApp referral data that the native flow drops.

        Meta only sends ``referral`` on the first message of a conversation that
        started from an ad. The native loop posts the message and discards the
        referral, so after the super() call we look up the freshly created
        message by ``msg_uid`` and store the attribution fields.
        """
        if 'messages' not in value and value.get('whatsapp_business_api_data', {}).get('messages'):
            value = value['whatsapp_business_api_data']
        Message = self.env['whatsapp.message'].sudo()
        for item in value.get('messages', []):
            referral = item.get('referral') or {}
            source_id = str(referral.get('source_id') or '').strip()
            if not source_id or not item.get('id'):
                continue
            message = Message.search([('msg_uid', '=', item['id'])], limit=1)
            if not message or message.referral_source_id:
                continue
            message.write({
                'referral_source_id': source_id[:64],
                'referral_source_url': referral.get('source_url'),
                'referral_ctwa_clid': referral.get('ctwa_clid'),
                'referral_captured_at': fields.Datetime.now(),
            })


class WhatsappMessage(models.Model):
    _inherit = 'whatsapp.message'

    referral_source_id = fields.Char(
        string='Ad ID de origen (Meta)',
        readonly=True,
        copy=False,
        index=True,
    )
    referral_source_url = fields.Char(string='URL del anuncio', readonly=True, copy=False)
    referral_ctwa_clid = fields.Char(string='CTWA Click ID', readonly=True, copy=False)
    referral_captured_at = fields.Datetime(string='Referral capturado', readonly=True, copy=False)

    def write(self, vals):
        result = super().write(vals)
        if vals.get('referral_source_id'):
            self._creative_lab_attribute()
        return result

    def _creative_lab_attribute(self):
        """Turn an ad-referred inbound message into a confirmed outcome."""
        Outcome = self.env['creative.outcome'].sudo()
        for message in self.filtered('referral_source_id'):
            if not message.msg_uid:
                continue
            publication = self.env['creative.publication'].sudo().search(
                [('external_ad_id', '=', message.referral_source_id)],
                limit=1,
            )
            if not publication:
                _logger.info(
                    'Creative Lab: referral %s sin publicación conocida (mensaje %s).',
                    message.referral_source_id,
                    message.msg_uid,
                )
                continue
            if Outcome.search_count([('whatsapp_message_id', '=', message.msg_uid)]):
                continue
            partner = message._creative_lab_channel_partner()
            lead = message._creative_lab_related_lead(partner)
            outcome = Outcome.create({
                'name': _('Conversación WhatsApp — %s') % (
                    partner.name if partner else message.mobile_number_formatted or message.msg_uid
                ),
                'publication_id': publication.id,
                'event_type': 'conversation',
                'source': 'whatsapp',
                'confirmed': True,
                'confidence': 1.0,
                'whatsapp_message_id': message.msg_uid,
                'referral_ad_id': message.referral_source_id,
                'partner_id': partner.id if partner else False,
                'lead_id': lead.id if lead else False,
                'evidence': '\n'.join(filter(None, [
                    'Referral CTWA confirmado por Meta.',
                    'source_id: %s' % message.referral_source_id,
                    'ctwa_clid: %s' % (message.referral_ctwa_clid or '-'),
                    'source_url: %s' % (message.referral_source_url or '-'),
                ])),
            })
            publication.message_post(body=_(
                'Nueva conversación atribuida desde WhatsApp: %s.'
            ) % outcome.display_name)

    def _creative_lab_channel_partner(self):
        self.ensure_one()
        mail_message = self.mail_message_id
        if mail_message and mail_message.model == 'discuss.channel' and mail_message.res_id:
            channel = self.env['discuss.channel'].sudo().browse(mail_message.res_id).exists()
            if channel and channel.whatsapp_partner_id:
                return channel.whatsapp_partner_id
        return self.env['res.partner'].browse()

    def _creative_lab_related_lead(self, partner):
        self.ensure_one()
        Lead = self.env['crm.lead'].sudo()
        if partner:
            lead = Lead.search(
                [('partner_id', '=', partner.id), ('active', '=', True)],
                order='create_date desc',
                limit=1,
            )
            if lead:
                return lead
        digits = ''.join(
            character for character in (self.mobile_number_formatted or '')
            if character.isdigit()
        )
        if len(digits) >= 8:
            return Lead.search(
                [('phone_sanitized', 'like', digits[-10:]), ('active', '=', True)],
                order='create_date desc',
                limit=1,
            )
        return Lead.browse()
