# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class CreativeBrief(models.Model):
    _name = 'creative.brief'
    _description = 'Brief creativo'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _check_company_auto = True

    name = fields.Char(string='Nombre', required=True, tracking=True)
    code = fields.Char(
        string='Código',
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _('Nuevo'),
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
        readonly=True,
    )
    project_id = fields.Many2one(
        'project.project',
        string='Proyecto',
        required=True,
        check_company=True,
        tracking=True,
        ondelete='restrict',
    )
    campaign_id = fields.Many2one(
        'utm.campaign',
        string='Campaña UTM',
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
            ('ready', 'Brief aprobado'),
            ('in_progress', 'En producción'),
            ('review', 'En revisión'),
            ('done', 'Finalizado'),
            ('cancelled', 'Cancelado'),
        ],
        string='Estado',
        default='draft',
        required=True,
        tracking=True,
        index=True,
    )

    brand_name = fields.Char(string='Marca')
    objective = fields.Text(string='Objetivo', tracking=True)
    offer = fields.Text(string='Oferta', tracking=True)
    target_audience = fields.Text(string='Público objetivo', tracking=True)
    pains = fields.Text(string='Dolores')
    desires = fields.Text(string='Deseos')
    objections = fields.Text(string='Objeciones')
    proof = fields.Text(string='Pruebas y afirmaciones respaldadas')
    brand_guidelines = fields.Text(string='Guía de marca')
    constraints = fields.Text(string='Restricciones y políticas')
    expected_action = fields.Char(string='Acción esperada', default='Enviar un mensaje')
    initial_prompt = fields.Text(string='Prompt inicial')
    initial_file = fields.Binary(string='Archivo inicial', attachment=True)
    initial_filename = fields.Char(string='Nombre del archivo inicial')
    budget = fields.Monetary(string='Presupuesto experimental')

    hypothesis_ids = fields.One2many(
        'creative.hypothesis',
        'brief_id',
        string='Hipótesis',
    )
    creative_ids = fields.One2many(
        'creative.asset',
        'brief_id',
        string='Creativos',
    )
    hypothesis_count = fields.Integer(compute='_compute_counts')
    creative_count = fields.Integer(compute='_compute_counts')
    version_count = fields.Integer(compute='_compute_counts')

    @api.depends('hypothesis_ids', 'creative_ids', 'creative_ids.version_ids')
    def _compute_counts(self):
        for brief in self:
            brief.hypothesis_count = len(brief.hypothesis_ids)
            brief.creative_count = len(brief.creative_ids)
            brief.version_count = sum(len(item.version_ids) for item in brief.creative_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if (
                vals.get('state', 'draft') != 'draft'
                and not self.env.context.get('allow_workflow_write')
            ):
                raise AccessError(_('El estado inicial del brief debe ser borrador.'))
            if vals.get('code', _('Nuevo')) == _('Nuevo'):
                vals['code'] = self.env['ir.sequence'].next_by_code('creative.brief') or _('Nuevo')
        return super().create(vals_list)

    def write(self, vals):
        if 'state' in vals and not self.env.context.get('allow_workflow_write'):
            raise AccessError(_('Usá las acciones del brief para cambiar su estado.'))
        return super().write(vals)

    @api.constrains('project_id', 'company_id')
    def _check_project_company(self):
        for brief in self:
            if brief.project_id.company_id and brief.project_id.company_id != brief.company_id:
                raise ValidationError(_('El proyecto y el brief deben pertenecer a la misma compañía.'))

    def action_mark_ready(self):
        for brief in self:
            missing = []
            if not brief.objective:
                missing.append(_('objetivo'))
            if not brief.offer:
                missing.append(_('oferta'))
            if not brief.target_audience:
                missing.append(_('público objetivo'))
            if missing:
                raise ValidationError(
                    _('Completá los campos mínimos antes de aprobar el brief: %s.')
                    % ', '.join(missing)
                )
            brief.with_context(allow_workflow_write=True).write({'state': 'ready'})

    def action_start(self):
        for brief in self:
            if brief.state not in ('ready', 'review'):
                raise ValidationError(_('Solo un brief aprobado o en revisión puede pasar a producción.'))
            brief.with_context(allow_workflow_write=True).write({'state': 'in_progress'})

    def action_review(self):
        for brief in self:
            if not brief.creative_ids:
                raise ValidationError(_('Creá al menos un creativo antes de enviar el brief a revisión.'))
            brief.with_context(allow_workflow_write=True).write({'state': 'review'})

    def action_done(self):
        for brief in self:
            if not brief.creative_ids.filtered(lambda item: item.state == 'approved'):
                raise ValidationError(_('Debe existir al menos un creativo aprobado.'))
            brief.with_context(allow_workflow_write=True).write({'state': 'done'})

    def action_cancel(self):
        self.with_context(allow_workflow_write=True).write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.with_context(allow_workflow_write=True).write({'state': 'draft'})

    def action_view_hypotheses(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Hipótesis — %s') % self.display_name,
            'res_model': 'creative.hypothesis',
            'view_mode': 'list,form',
            'domain': [('brief_id', '=', self.id)],
            'context': {'default_brief_id': self.id},
        }

    def action_view_creatives(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Creativos — %s') % self.display_name,
            'res_model': 'creative.asset',
            'view_mode': 'kanban,list,form',
            'domain': [('brief_id', '=', self.id)],
            'context': {'default_brief_id': self.id},
        }

    def action_open_agent_wizard(self):
        self.ensure_one()
        profile = self.env['creative.agent.profile'].search([
            ('company_id', '=', self.company_id.id),
            ('role', '=', 'strategist'),
            ('task_type', '=', 'text'),
            ('active', '=', True),
        ], limit=1)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ejecutar agente sobre el brief'),
            'res_model': 'creative.agent.run.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_brief_id': self.id,
                'default_profile_id': profile.id,
                'default_operation': 'strategy',
            },
        }
