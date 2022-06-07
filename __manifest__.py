{
    'name': 'Klaviyo Email Integration',
    'version': '1.1',
    'author': 'Kyle Waid',
    'category': 'Sales Management',
    'depends': ['integrator_netsuite'],
    'website': 'https://www.gcotech.com',
    'description': """
    """,
    'data': [
             'security/ir.model.access.csv',
             'views/klaviyo.xml',
             'views/job.xml',
    ],
    'test': [
    ],
    'installable': True,
    'auto_install': False,
    'external_dependencies': {
        'python': ['klaviyo'],
    },
}
