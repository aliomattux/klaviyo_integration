from odoo import api, fields, models, SUPERUSER_ID, _

class NetsuiteJob(models.Model):
    _inherit = 'netsuite.job'

    klaviyo_event_name = fields.Char('Klaviyo Event Name')
