{
    'name': 'Creative Lab AI',
    'version': '19.0.1.0.1',
    'category': 'Marketing',
    'summary': 'Creación, versionado, aprobación y atribución de creativos con IA',
    'description': """
Creative Lab AI
===============

Workspace de operaciones creativas integrado con Proyecto, CRM y LLM Connector.
Permite definir briefs e hipótesis, generar o editar activos mediante agentes,
mantener un linaje inmutable de versiones, aprobar entregables, limpiar
metadatos y registrar publicaciones y resultados comerciales.
    """,
    'author': 'Aftermoves',
    'license': 'LGPL-3',
    'depends': [
        'mail',
        'project',
        'crm',
        'utm',
        'llm_connector',
    ],
    'data': [
        'security/creative_lab_security.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'data/agent_profile_data.xml',
        'wizard/generate_creative_wizard_views.xml',
        'wizard/run_agent_wizard_views.xml',
        'wizard/export_asset_wizard_views.xml',
        'views/creative_brief_views.xml',
        'views/creative_hypothesis_views.xml',
        'views/creative_asset_views.xml',
        'views/creative_agent_views.xml',
        'views/creative_distribution_views.xml',
        'views/project_project_views.xml',
        'views/creative_lab_menus.xml',
    ],
    'application': True,
    'installable': True,
}
