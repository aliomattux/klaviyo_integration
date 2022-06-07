from odoo import api, fields, models, SUPERUSER_ID, _

class KlaviyoEvent(models.Model):
    _name = 'klaviyo.event'
    _rec_name = 'record_id'
    create_date = fields.Datetime('Create Date')
    record_id = fields.Char('Record ID')
    recordtype = fields.Char('Record Type')
