from odoo import api, fields, models, SUPERUSER_ID, _, exceptions
from datetime import datetime, timedelta
from pprint import pprint as pp
from time import sleep
import logging
_logger = logging.getLogger(__name__)


class KlaviyoIntegrator(models.TransientModel):
    _inherit = 'klaviyo.integrator'


    def execute_klaviyo_tracking_events(self, job):
        netsuite_obj = self.env['netsuite.integrator']

        vals = {
                'search_id': job.search_id,
                'record_type': 'transaction',
        }

        try:
            _logger.info('Downloading fulfillment data from Netsuite')
            conn = netsuite_obj.connection(job.netsuite_instance)
            response = conn.saved(vals)

        except Exception as e:
            subject = 'Could not get fulfillment data from Netsuite'
            self.env['integrator.logger'].submit_event('Klaviyo', subject, str(e), False, 'admin')
            return False

        try:
            fulfillments = self.process_fulfillment_data(response['data'])
        except Exception as e:
            subject = 'Could not process fulfillment data'
            self.env['integrator.logger'].submit_event('Klaviyo', subject, str(e), False, 'admin')
            return False

        sent_fulfillments = self.send_tracking_events(fulfillments)

        if sent_fulfillments:
            return self.upsert_klaviyo_netsuite_fields(conn, sent_fulfillments)

        return True


    def process_fulfillment_data(self, response_data):
        fulfillments = {}
        for each in response_data:
            record = each['columns']
            record_id = record['internalid']['internalid']
            if fulfillments.get(record_id):
                fulfillments[record_id]['properties']['Items'].append(self.convert_fulfillment_line(record))
            else:
                fulfillments[record_id] = self.convert_fulfillment(record)

        return fulfillments


    def send_tracking_events(self, fulfillments):
        fulfillment_data = []
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

        for fulfillment_id, fulfillment in fulfillments.items():
            event_already_sent = self.find_klaviyo_event(fulfillment_id, 'itemfulfillment')
            if event_already_sent:
                fulfillment_data.append({
                    'id': fulfillment_id,
                    'type': 'itemfulfillment',
                    'field': 'custbody_k_shipment_notice_sent',
                    'value': 'T'
                })

                continue

            if error_count >= error_max_count:
#                subject = 'Warning: Max Error count exceeded for tracking emails!'
 #               self.env['integrator.logger'].submit_event('klaviyo', subject, 'No Trace', False, 'admin')
                return fulfillment_data

            if not fulfillment['customer_properties'].get('$email'):
                fulfillment_data.append({
                    'id': fulfillment_id,
                    'type': 'itemfulfillment',
                    'field': 'custbody_k_shipment_notice_sent',
                    'value': 'T'
                })

                continue

#                subject = 'Fulfillment: %s Has no email address to send to.' % fulfillment_id
#                self.env['integrator.logger'].submit_event('klaviyo', subject, 'No Trace', False, 'admin')
#                continue
            try:
                response = self.send_klaviyo_request(klaviyo, fulfillment)
                self.store_klaviyo_event_sent(fulfillment_id, 'itemfulfillment')
                sleep(0.3)

            except Exception as e:
#                subject = 'Could not map and or send email in klaviyo for Fulfillment: %s'%fulfillment_id
 #               self.env['integrator.logger'].submit_event('klaviyo', subject, str(e), False, 'admin')
                error_count += 1
                continue

            fulfillment_data.append({
                'id': fulfillment_id,
                'type': 'itemfulfillment',
                'field': 'custbody_k_shipment_notice_sent',
                'value': 'T'
            })

            count += 1
            if count > max:
                break

        return fulfillment_data


    def convert_fulfillment(self, record):
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

        tracking_numbers = record['formulatext']
        tracking_numbers = tracking_numbers.replace('UPS\t', '')
        tracking_numbers = tracking_numbers.split('<BR>')
        shipmethod = record.get('shipmethod')
        if shipmethod:
            shipmethod = record['shipmethod']['name']
        else:
            shipmethod = 'No Shipping method'

        custom_carrier = record.get('custbody_custom_carrier')
        if custom_carrier:
            custom_carrier = record['custbody_custom_carrier']['name']

        custom_tracking_link = record.get('custrecord_carrier_tracking_link')

        ltl_carrier, tracking_data = self.explode_tracking_numbers(\
            shipmethod, tracking_numbers, custom_carrier, custom_tracking_link
        )

        if shipmethod.lower() == 'ltl':
            shipmethod = ltl_carrier

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

        primary_tracking_data = {}

        if tracking_data:
            primary_tracking_data = tracking_data[0]

        return {
            'customer_properties': {
                '$email': email,
            },
            'event': 'Shipped Order',
            'properties': {
                'OrderID': sales_order_number,
                'TrackingNumbers': tracking_data,
                'ShippingAddress': ship_address,
                'ShippingMethod': shipmethod,
                'ShipName': ship_name,
                'ShipDate': shipdate,
                'PrimaryTrackingNumber': primary_tracking_data.get('tracking_number'),
                'PrimaryTrackingLink': primary_tracking_data.get('tracking_link'),
                'Items': [self.convert_fulfillment_line(record)],
             },
        }


    def convert_fulfillment_line(self, record):
        product_obj = self.env['product']

        qty = record['quantity']
        sku = record['custitem36']
        item_id = record['item']['internalid']

        description = record.get('purchasedescription')
        description = description.replace('.', '')
        sku = sku.replace('.', '')
        options = record.get('custcol_custom_options')
        options = self.explode_item_options(options)
        return {
           'internalid': item_id,
            'sku': sku,
            'description': description,
            'fulfillment_line_qty': qty,
            'options': options
        }


    def explode_tracking_numbers(self, shipmethod, tracking_numbers, custom_carrier, custom_tracking_link):
        res = []
        shipmethod = shipmethod.lower()
        detected_carrier = ""
        tracking_prefix = False
        tracking_suffix = False

        if custom_carrier:
            tracking_suffix = False
            tracking_prefix = custom_tracking_link
            detected_carrier = custom_carrier
        elif 'ups freight' in shipmethod:
            tracking_prefix = 'https://www.tforcefreight.com/ltl/apps/Tracking?proNumbers='
            tracking_suffix = ';'
            detected_carrier = 'Tforce Freight'

        elif 'tforce' in shipmethod:
            tracking_prefix = 'https://www.tforcefreight.com/ltl/apps/Tracking?proNumbers='
            tracking_suffix = ';'
            detected_carrier = 'Tforce Freight'

        elif 'ups' in shipmethod:
            tracking_prefix = 'https://www.ups.com/track?loc=null&tracknum='
            tracking_suffix = '&requester=WT/trackdetails'
            detected_carrier = 'UPS'

        elif 'usps' in shipmethod:
            tracking_prefix = 'https://tools.usps.com/go/TrackConfirmAction?qtc_tLabels1='
            tracking_suffix = False
            detected_carrier = 'USPS'

        elif 'fedex' in shipmethod:
            tracking_prefix = 'https://www.fedex.com/fedextrack/?trknbr='
            tracking_suffix = ''
            detected_carrier = 'Fedex'

        elif shipmethod.lower() == 'ltl':
            for tracking in tracking_numbers:
                tracking = tracking.lower()
                if '1z' in tracking:
                    detected_carrier = 'UPS'
                    tracking_prefix = 'https://www.ups.com/track?loc=null&tracknum='
                    tracking_suffix = '&requester=WT/trackdetails'
                    break
                elif 'aduie' in tracking:
                    detected_carrier = 'A. Duie Pyle'
                    tracking_prefix = 'https://www.aduiepyle.com/LTL/ShipmentTracking?Pro='
                    tracking_suffix = False
                    break
                elif 'dominion' in tracking:
                    detected_carrier = 'Old Dominion'
                    tracking_prefix = 'https://www.odfl.com/Trace/standardResult.faces?pro='
                    tracking_suffix = False
                    break
                elif 'dayton' in tracking:
                    detected_carrier = 'Dayton'
                    tracking_prefix = 'https://tools.daytonfreight.com/tracking/detail/'
                    tracking_suffix = False
                    break
                elif 'ohio' in tracking:
                    detected_carrier = 'Pitt Ohio'
                    tracking_prefix = 'https://pittohio.com/myPittOhio/Shipping/QuickTrace/Post?TrackingNumbers='
                    tracking_suffix = False
                    break
                elif 'xpo' in tracking:
                    detected_carrier = 'XPO'
                    tracking_prefix = 'https://app.ltl.xpo.com/appjs/tracking/details/'
                    tracking_suffix = False
                    break
                elif len(tracking) == '12':
                    detected_carrier = 'FedEx Freight'
                    tracking_prefix = 'https://www.fedex.com/apps/fedextrack/?tracknumbers='
                    tracking_suffix = ''
                    break
                elif len(tracking) == '15':
                    detected_carrier = 'FedEx Freight'
                    tracking_prefix = 'https://www.fedex.com/apps/fedextrack/?tracknumbers='
                    tracking_suffix = ''
                    break

        for tracking_number in tracking_numbers:
            tracking_number = self.cleanse_tracking_number(tracking_number)
            tracking_link = False
            if tracking_prefix:
                tracking_link = tracking_prefix + tracking_number
                if tracking_suffix:
                    tracking_link += tracking_suffix

            res.append({
                'tracking_link': tracking_link,
                'tracking_number': tracking_number
            })

        return detected_carrier, res


    def cleanse_tracking_number(self, tracking_number):
        tracking_number = tracking_number.lower()
        tracking_number = tracking_number.replace('UPS      ', '')
        tracking_number = tracking_number.replace('#', '')
        tracking_number = tracking_number.replace(':', '')
        if 'ohio' in tracking_number:
            tracking_number = tracking_number.replace('pittohiopro', '')
        elif 'dominion' in tracking_number:
            tracking_number = tracking_number.replace('olddominionpro', '')
            tracking_number = tracking_number.replace('olddominion', '')
        elif 'fedexfreight' in tracking_number:
            tracking_number = tracking_number.replace('fedexfreight', '')
        elif 'xpo' in tracking_number:
            tracking_number = tracking_number.replace('xpo', '')
        elif 'dayton' in tracking_number:
            tracking_number = tracking_number.replace('dayton', '')
        elif 'aduie' in tracking_number:
            tracking_number = tracking_number.replace('aduie', '')
        tracking_number = tracking_number.strip()
        return tracking_number
