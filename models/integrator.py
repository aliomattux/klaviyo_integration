from odoo import api, fields, models, SUPERUSER_ID, _, exceptions
from datetime import datetime, timedelta
import requests
import base64
import json

import logging
_logger = logging.getLogger(__name__)

class KlaviyoIntegrator(models.TransientModel):
    _name = 'klaviyo.integrator'


    def encode_parameters(self, data):
        return base64.b64encode(json.dumps(data).encode('utf-8'))


    def send_klaviyo_request(self, klaviyo, data):
        data['token'] = klaviyo.private_key
        data = self.encode_parameters(data)

        params = {
            'data': data
        }

        headers = {
            'Content-Type': 'application/json',
#            'User-Agent': 'DecksDirect Integrator'
        }

        url = 'https://a.klaviyo.com/api/track'

        response = requests.get(url, headers=headers, params=params)

        print('Response')
        print(response)
        print('Content')
        print(response.content)
 #       if delivery.results[0].isError == True:
  #          raise exceptions.UserError('Delivery result is error')
   #     else:
    #        _logger.info('The delivery has been sent. The delivery ID is: ' + delivery.results[0].id)
        return True


    def explode_item_options(self, options):
        """'custcol_custom_options': u'Quantity: 100 Handi-Pak\nSize: 5/16"x 3-1/2"'"""
        """<tr>
            <td style="padding-left: 15px;">
                <strong>Size: </strong><span style="font-style: italic;">12 in.</span>
            </td>
        </tr>"""
        res = []
        if not options:
            return res

        options = options.split('\n')
        for option in options:
            option_data = option.split(': ')
            option_name = option_data[0]
            option_value = option_data[1]
            res.append({
                'name': option_name,
                'value': option_value,
            })

        return res


    def upsert_klaviyo_netsuite_fields(self, conn, data):
        try:
            data = {'records': data}
            response = conn.upsert(data)
#            if response.get('data') and response['data'].get('errors'):
 #               subject = 'Netsuite Upsert completed with Errors'
  #              self.env['integrator.logger'].submit_event('Klaviyo', subject, str(response['data']['errors']), False, 'admin')
        except Exception as e:
            subject = 'Could not upsert record to Netsuite'
            self.env['integrator.logger'].submit_event('Netsuite', subject, str(e), False, 'admin')

        return True


    def find_klaviyo_event(self, record_id, recordtype):
        sent_obj = self.env['klaviyo.event']
        emails = sent_obj.search([
            ('record_id', '=', record_id),
            ('recordtype', '=', recordtype)
        ])

        if emails:
            return True

        return False


    def store_klaviyo_event_sent(self, record_id, recordtype):
        sent_obj = self.env['klaviyo.event']

        return sent_obj.create({
            'record_id': record_id,
            'recordtype': recordtype,
        })

