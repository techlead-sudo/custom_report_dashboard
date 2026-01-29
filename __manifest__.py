{
    'name': 'Custom Dashboard',
    'version': '1.0',
    'summary': 'Dashboard for graphical and chart-based reports',
    'author': 'Your Company',
    'category': 'Reporting',
    'depends': ['base', 'hr'],
    'data': [
        'security/dashboard_security.xml',
        'security/ir.model.access.csv',
        'views/dashboard_report_views.xml',
        'data/dashboard_report_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'custom_report_dashboard/static/src/css/dashboard_report.css',
        ],
    },
    'installable': True,
    'application': True,
}
