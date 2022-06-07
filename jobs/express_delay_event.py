from odoo import api, fields, models, SUPERUSER_ID, _, exceptions
from datetime import datetime, timedelta
from pprint import pprint as pp
from time import sleep
import logging
_logger = logging.getLogger(__name__)


class KlaviyoIntegrator(models.TransientModel):
    _inherit = 'klaviyo.integrator'


    def execute_klaviyo_express_delay_events(self, job):
        netsuite_obj = self.env['netsuite.integrator']

        vals = {
                'search_id': job.search_id,
                'record_type': 'transaction',
        }

        try:
            _logger.info('Downloading Express Delay Sales data from Netsuite')
            conn = netsuite_obj.connection(job.netsuite_instance)
            response = conn.saved(vals)

        except Exception as e:
            subject = 'Could not get Express Delay Sales data from Netsuite'
            self.env['integrator.logger'].submit_event('klaviyo', subject, str(e), False, 'admin')
            return False

        try:
            express_sales = self.process_express_delay_sales_data(response['data'])
        except Exception as e:
            subject = 'Could not process express delay sales data'
            self.env['integrator.logger'].submit_event('klaviyo', subject, str(e), False, 'admin')
            return False

        sent_express_delay_sales = self.send_express_delay_events(express_sales)

        if sent_express_delay_sales:
            return self.upsert_klaviyo_netsuite_fields(conn, sent_express_delay_sales)

        return True


    def process_express_delay_sales_data(self, response_data):
        express_sales = {}
        for each in response_data:
            record = each['columns']
            record_id = record['internalid']['internalid']
            express_sales[record_id] = self.convert_express_delay_sale(record)

        return express_sales


    def send_express_delay_events(self, express_sales):
        express_sales_data = []
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

        for sale_id, express_sale in express_sales.items():
            event_already_sent = self.find_klaviyo_event(sale_id, 'express_sales_delay')
            if event_already_sent:
                express_sales_data.append({
                    'id': sale_id,
                    'type': 'salesorder',
                    'field': 'custbody_carrier_express_delay_e_date',
                    'value': 'datetime'
                })
                continue

            if error_count >= error_max_count:
#                subject = 'Warning: Max Error count exceeded for tracking emails!'
 #               self.env['integrator.logger'].submit_event('klaviyo', subject, 'No Trace', False, 'admin')
                return express_sales_data

            if not express_sale['customer_properties'].get('$email'):
                express_sales_data.append({
                    'id': sale_id,
                    'type': 'salesorder',
                    'field': 'custbody_carrier_express_delay_e_date',
                    'value': 'datetime'
                })

                continue

#                subject = 'Fulfillment: %s Has no email address to send to.' % fulfillment_id
#                self.env['integrator.logger'].submit_event('klaviyo', subject, 'No Trace', False, 'admin')
#                continue

            try:
                response = self.send_klaviyo_request(klaviyo, express_sale)
                self.store_klaviyo_event_sent(sale_id, 'express_sales_delay')
                sleep(0.3)

            except Exception as e:
#                subject = 'Could not map and or send email in klaviyo for Fulfillment: %s'%fulfillment_id
 #               self.env['integrator.logger'].submit_event('klaviyo', subject, str(e), False, 'admin')
                error_count += 1
                continue

            express_sales_data.append({
                'id': sale_id,
                'type': 'salesorder',
                'field': 'custbody_carrier_express_delay_e_date',
                'value': 'datetime'
            })

            count += 1
            if count > max:
                break

        return express_sales_data


    def convert_express_delay_sale(self, record):
        """{'custbody25': 'koscheski@charter.net',
         'entity': {'internalid': '8023059', 'name': '230816 Caroll Koscheski'},
         'internalid': {'internalid': '15124823', 'name': '15124823'},
         'shipaddressee': 'Caroll Koscheski',
         'shipcity': 'Hickory',
         'shipmethod': {'internalid': '996', 'name': 'FedEx 2Day®'},
         'shippingattention': 'Caroll Koscheski',
         'shipstate': 'NC',
         'shipzip': '28601-9017',
         'tranid': '100351845'}"""

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
            'event': 'Express Potential Delay Notice',
            'properties': {
                'OrderID': sales_order_number,
                'ShippingName': ship_name,
             },
        }


