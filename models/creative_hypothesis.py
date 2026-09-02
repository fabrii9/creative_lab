# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class CreativeHypothesis(models.Model):
    _name = 'creative.hypothesis'
    _description = 'Hipótesis creativa de marketing'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'priority desc, id desc'
    _check_company_auto = True

    name = fields.Char(string='Hipótesis', required=True, tracking=True)
    active = fields.Boolean(default=True)
    brief_id = fields.Many2one(
        'creative.brief',
        string='Brief',
        required=True,
        ondelete='cascade',
        check_company=True,
        tracking=True,
        index=True,
    )
    company_id = fields.Many2one(
        related='brief_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    state = fields.Selection(
        [
            ('draft', 'Borrador'),
            ('selected', 'Seleccionada'),
            ('testing', 'En prueba'),
            ('learned', 'Aprendizaje registrado'),
            ('rejected', 'Descartada'),
        ],
        default='draft',
        required=True,
        tracking=True,
        index=True,
    )
    priority = fields.Selection(
        [('0', 'Normal'), ('1', 'Alta'), ('2', 'Muy alta')],
        default='0',
    )
    segment = fields.Text(string='Segmento', required=True)
    pain = fields.Text(string='Dolor')
    desire = fields.Text(string='Deseo')
    objection = fields.Text(string='Objeción')
    awareness_level = fields.Selection(
        [
            ('unaware', 'No consciente'),
            ('problem', 'Consciente del problema'),
            ('solution', 'Consciente de la solución'),
            ('product', 'Consciente del producto'),
            ('most', 'Muy consciente'),
        ],
        string='Nivel de conciencia',
        required=True,
        default='problem',
    )
    sophistication_level = fields.Selection(
        [('1', '1 · Mercado nuevo'), ('2', '2'), ('3', '3'), ('4', '4'), ('5', '5 · Muy sofisticado')],
        string='Sofisticación del mercado',
        required=True,
        default='1',
    )
    angle = fields.Text(string='Ángulo')
    hook = fields.Text(string='Hook')
    expected_action = fields.Char(string='Respuesta esperada')
    rationale = fields.Text(string='Por qué debería funcionar')
    learning = fields.Text(string='Aprendizaje')
    creative_ids = fields.One2many('creative.asset', 'hypothesis_id', string='Creativos')
    creative_count = fields.Integer(compute='_compute_creative_count')

    @api.depends('creative_ids')
    def _compute_creative_count(self):
        for hypothesis in self:
            hypothesis.creative_count = len(hypothesis.creative_ids)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('allow_workflow_write'):
            for vals in vals_list:
                if vals.get('state', 'draft') != 'draft':
                    raise AccessError(_('El estado inicial de la hipótesis debe ser borrador.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'state' in vals and not self.env.context.get('allow_workflow_write'):
            raise AccessError(_('Usá las acciones de la hipótesis para cambiar su estado.'))
        return super().write(vals)

    @api.constrains('brief_id', 'company_id')
    def _check_hypothesis_company(self):
        for hypothesis in self:
            if hypothesis.company_id != hypothesis.brief_id.company_id:
                raise ValidationError(_('La hipótesis debe usar la compañía de su brief.'))

    def action_select(self):
        self.with_context(allow_workflow_write=True).write({'state': 'selected'})

    def action_testing(self):
        for hypothesis in self:
            if not hypothesis.creative_ids:
                raise ValidationError(_('La hipótesis necesita al menos un creativo para entrar en prueba.'))
            hypothesis.with_context(allow_workflow_write=True).write({'state': 'testing'})

    def action_learned(self):
        for hypothesis in self:
            if not hypothesis.learning:
                raise ValidationError(_('Registrá el aprendizaje antes de cerrar la hipótesis.'))
            hypothesis.with_context(allow_workflow_write=True).write({'state': 'learned'})

    def action_reject(self):
        self.with_context(allow_workflow_write=True).write({'state': 'rejected'})
