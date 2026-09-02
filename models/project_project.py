# -*- coding: utf-8 -*-

from odoo import _, api, fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    creative_brief_ids = fields.One2many('creative.brief', 'project_id', string='Briefs creativos')
    creative_brief_count = fields.Integer(compute='_compute_creative_brief_count')

    @api.depends('creative_brief_ids')
    def _compute_creative_brief_count(self):
        for project in self:
            project.creative_brief_count = len(project.creative_brief_ids)

    def action_view_creative_briefs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Briefs creativos — %s') % self.display_name,
            'res_model': 'creative.brief',
            'view_mode': 'kanban,list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {
                'default_project_id': self.id,
                'default_company_id': self.company_id.id or self.env.company.id,
            },
        }
