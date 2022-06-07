from odoo import api, fields, models, SUPERUSER_ID, _

class KlaviyoSetup(models.Model):
    _name = 'klaviyo.setup'
    name = fields.Char('Name', required=True)
    public_key = fields.Char('Public Key', required=True)
    private_key = fields.Char('Private Key', required=True)
