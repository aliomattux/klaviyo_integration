from odoo import api, fields, models, SUPERUSER_ID, _, exceptions
from datetime import datetime, timedelta
from pprint import pprint as pp
from time import sleep
import logging
_logger = logging.getLogger(__name__)


class KlaviyoIntegrator(models.TransientModel):
    _inherit = 'klaviyo.integrator'


    def execute_klaviyo_ltl_shipping_confirmation_events(self, job):
        netsuite_obj = self.env['netsuite.integrator']

        vals = {
                'search_id': job.search_id,
                'record_type': 'transaction',
        }

        try:
            _logger.info('Downloading LTL Agreement Sales data from Netsuite')
            conn = netsuite_obj.connection(job.netsuite_instance)
            response = conn.saved(vals)

        except Exception as e:
            subject = 'Could not get LTL Agreement Sales data from Netsuite'
            self.env['integrator.logger'].submit_event('klaviyo', subject, str(e), False, 'admin')
            return False

        try:
            agreements = self.process_ltl_agreement_data(response['data'])

        except Exception as e:
            subject = 'Could not process ltl agreement sales data'
            self.env['integrator.logger'].submit_event('klaviyo', subject, str(e), False, 'admin')
            return False

        sent_agreements = self.send_agreement_events(agreements)

        if sent_agreements:
            return self.upsert_klaviyo_netsuite_fields(conn, sent_agreements)

        return True


    def process_ltl_agreement_data(self, response_data):
        agreements = {}
        for each in response_data:
            record = each['columns']
            record_id = record['internalid']['internalid']
            agreements[record_id] = self.convert_agreement(record)

        return agreements


    def send_agreement_events(self, agreements):
        agreement_data = []
        max = 20
        count = 0
        error_max_count = 5
        error_count = 0
        setup_obj = self.env['klaviyo.setup']
        klaviyo = setup_obj.search([])
        if not klaviyo:
            print('No Klaviyo')
            return True

        klaviyo = klaviyo[0]

        for fulfillment_id, agreement in agreements.items():
            event_already_sent = self.find_klaviyo_event(fulfillment_id, 'ltlagreement')
            if event_already_sent:
                agreement_data.append({
                    'id': fulfillment_id,
                    'type': 'itemfulfillment',
                    'field': 'custbody_k_ltl_confirmation_sent_date',
                    'value': 'datetime'
                })
                continue

            if error_count >= error_max_count:
#                subject = 'Warning: Max Error count exceeded for tracking emails!'
 #               self.env['integrator.logger'].submit_event('klaviyo', subject, 'No Trace', False, 'admin')
                return agreement_data

            if not agreement['customer_properties'].get('$email'):
                agreement_data.append({
                    'id': fulfillment_id,
                    'type': 'itemfulfillment',
                    'field': 'custbody_k_ltl_confirmation_sent_date',
                    'value': 'datetime'
                })

                continue

#                subject = 'Fulfillment: %s Has no email address to send to.' % fulfillment_id
#                self.env['integrator.logger'].submit_event('klaviyo', subject, 'No Trace', False, 'admin')
#                continue

            try:
                response = self.send_klaviyo_request(klaviyo, agreement)
                self.store_klaviyo_event_sent(fulfillment_id, 'ltlagreement')
                sleep(0.3)

            except Exception as e:
                _logger.critical(e)
#                subject = 'Could not map and or send email in klaviyo for Fulfillment: %s'%fulfillment_id
 #               self.env['integrator.logger'].submit_event('klaviyo', subject, str(e), False, 'admin')
                error_count += 1
                continue

            agreement_data.append({
                'id': fulfillment_id,
                'type': 'itemfulfillment',
                'field':'custbody_k_ltl_confirmation_sent_date',
                'value': 'datetime'
            })

            count += 1
            if count > max:
                break

        return agreement_data


    def convert_agreement(self, record):
        """{'columns': {u'custitem36': u'150PP',
              'formulatext': u'UPS1ze752370395933154',
              'custbody25': u'ctodd127@comcast.net'
              'internalid': {u'internalid': u'13734472',
                              u'name': u'13734472'},
              'shippingattention': u'Connie Todd',
              'shipaddressee': u'Donald Roberts',
              'item': {u'internalid': u'31154',
                        u'name': u'Lighting : TimberTech : tt_tsfmr : 150PP-tt_tsfmr-150w'},
              'options': u'CUSTCOL36\x03F\x03Type\x0389\x03150 Watt',
              'custcol_custom_options': u'Quantity: 100 Handi-Pak\nSize: 5/16"x 3-1/2"',
              'purchasedescription': u'Power Pack by Azek/TimberTech',
              'quantity': 1,
              'shipaddress': u'Connie Todd\n13545 Worleytown  RD\nGreencasle PA 17225',
              'shipmethod': {u'internalid': u'5599',
                              u'name': u'FedEx Home Delivery\xae'},
              'trandate': u'11/23/2020',
              'tranid': u'100317869'},
         'id': '13734472',
         'recordtype': 'itemfulfillment'}"""

        shipdate = record['trandate']
        ship_address = {
            'addressee': record.get('shipaddressee'),
            'attention': record.get('shippingattention'),
            'address1': record.get('shipaddress1'),
            'address2': record.get('shipaddress2'),
            'city': record.get('shipcity'),
            'state': record.get('shipstate'),
            'zip': record.get('shipzip')
        }

        sales_order_number = record['tranid']
        email = record.get('custbody25')
        ship_addressee = record.get('shipaddressee')
        ship_attention = record.get('shippingattention')
        ship_name = False
        if ship_attention:
            ship_name = ship_attention
        if ship_addressee:
            ship_name = ship_addressee

        return {
            'customer_properties': {
                '$email': email,
            },
            'event': 'LTL Shipping Confirmation Agreement',
            'properties': {
                'OrderID': sales_order_number,
                'ShippingName': ship_name,
            }
        }
