from odoo import api, fields, models, SUPERUSER_ID, _, exceptions
from datetime import datetime, timedelta
from pprint import pprint as pp
from time import sleep
import logging
_logger = logging.getLogger(__name__)

class KlaviyoIntegrator(models.TransientModel):
    _inherit = 'klaviyo.integrator'


    def execute_klaviyo_sale_confirmation_events(self, job):
        netsuite_obj = self.env['netsuite.integrator']

        vals = {
                'search_id': job.search_id,
                'record_type': 'transaction',
        }

        try:
            _logger.info('Downloading Sales data from Netsuite')
            conn = netsuite_obj.connection(job.netsuite_instance)
            response = conn.saved(vals)

        except Exception as e:
            subject = 'Could not get Sales data from Netsuite'
            self.env['integrator.logger'].submit_event('Klaviyo', subject, str(e), False, 'admin')
            return False

        try:
            sales = self.process_sales_data(response['data'])

        except Exception as e:
            subject = 'Could not process Sales data'
            self.env['integrator.logger'].submit_event('Klaviyo', subject, str(e), False, 'admin')
            return

        sent_sales = self.send_sale_confirmation_events(sales)

        if sent_sales:
            return self.upsert_klaviyo_netsuite_fields(conn, sent_sales)

        return True


    def process_sales_data(self, response_data):
        sales = {}
        for each in response_data:
            record = each['columns']
            record_id = record['internalid']['internalid']
            if sales.get(record_id):
                sales[record_id]['properties']['Items'].append(self.convert_sale_line(record))
            else:
                sales[record_id] = self.convert_sale(record)

        for sale_id, sale_vals in sales.items():
            subtotal = 0
            discount_amount = 0
            for line in sale_vals['properties']['Items']:
                subtotal += line['sale_line_amount']
                discount_amount += line['discount_amount']

            subtotal = round(subtotal, 2)
            discount_amount = round(discount_amount, 2)
            sales[sale_id]['properties']['Subtotal'] = '${:,.2f}'.format(subtotal)
            sales[sale_id]['properties']['DiscountAmount'] = '${:,.2f}'.format(discount_amount)

        return sales


    def send_sale_confirmation_events(self, sales):
        sale_data = []
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

        for sale_id, sale_params in sales.items():
            event_already_sent = self.find_klaviyo_event(sale_id, 'salesorder')
            if event_already_sent:
                sale_data.append({
                    'id': sale_id,
                    'type': 'salesorder',
                    'field': 'custbody_klaviyo_trans_email_sent',
                    'value': 'T'
                })

                continue

            if error_count >= error_max_count:
                print('TOO MANY ERROR')
                subject = 'Warning: Max Error count exceeded for tracking emails!'
                self.env['integrator.logger'].submit_event('Klaviyo', subject, 'No Trace', False, 'admin')
                return sale_data

            if not sale_params['customer_properties'].get('$email'):
                sale_data.append({
                    'id': sale_id,
                    'type': 'salesorder',
                    'field': 'custbody_klaviyo_trans_email_sent',
                    'value': 'T'
                })

                continue

#                subject = 'Sale: %s Has no email address to send to.' % sale_id
#                self.env['integrator.logger'].submit_event('Klaviyo', subject, 'No Trace', False, 'admin')
#                continue

            try:
                response = self.send_klaviyo_request(klaviyo, sale_params)
                self.store_klaviyo_event_sent(sale_id, 'salesorder')
                sleep(0.3)

            except Exception as e:
                print('ERROR')
                print(e)
                subject = 'Could not map and or send email in Klaviyo for Sale: %s'%sale_id
                self.env['integrator.logger'].submit_event('Klaviyo', subject, str(e), False, 'admin')
                error_count += 1
                continue

            sale_data.append({
                'id': sale_id,
                'type': 'salesorder',
                'field': 'custbody_klaviyo_trans_email_sent',
                'value': 'T'
            })

            count += 1
            if count > max:
                break

        return sale_data


    def convert_sale(self, record):
        """    {u'columns': {u'amount': 209.94,
                      u'custbody25': u'ultimatecare5@hotmail.com',
                      u'custcol_custom_options': u'Size: 3-5/8"\nMaterial Type: Vinyl\nFinish: White',
                      u'custitem36': u'1480W',
                      u'internalid': {u'internalid': u'13849133',
                                      u'name': u'13849133'},
                      u'item': {u'internalid': u'25126',
                                u'name': u'lmt_nptn_slr_pc : 1480W-lmt_nptn_slr_pc-358-vnyl-wht'},
                      u'options': u'CUSTCOL30\x03F\x03Size\x031\x033-5/8"\x04CUSTCOL31\x03F\x03Material Type\x0311\x03Vinyl\x04CUSTCOL33\x03F\x03Finish\x032\x03White',
                      u'purchasedescription': u'Neptune Solar Light Post Cap by LMT Mercer',
                      u'quantity': 6,
                      u'shipaddress': u'mitchell simon\n390 Bristol Stone Lane\nAlpharetta GA 30005-7289',
                      u'shipmethod': {u'internalid': u'5599',
                                      u'name': u'FedEx Home Delivery\xae'},
                      u'shippingattention': u'mitchell simon',
                      u'shippingcost': 0,
                      u'taxtotal': 20.04,
                      u'total': 278.58,
                      u'trandate': u'12/9/2020',
                      u'tranid': u'100319890'},
         u'id': u'13849133',
         u'recordtype': u'salesorder'}"""

        shipping_method = record.get('shipmethod')
        if not shipping_method:
            shipping_method = 'No Shipping Method'
        else:
            shipping_method = shipping_method.get('name')

        bill_address = {
            'addressee': record.get('billaddressee'),
            'attention': record.get('billattention'),
            'address1': record.get('billaddress1'),
            'address2': record.get('billaddress2'),
            'city': record.get('billcity'),
            'state': record.get('billstate'),
            'zip': record.get('billzip')
        }

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
        tax_total = record.get('taxtotal')
        grand_total = record.get('total')
        shipping_cost = record.get('shippingcost')
        if not shipping_cost:
            shipping_cost = 0
        if not tax_total:
            tax_total = 0

        tax_total = '${:,.2f}'.format(float(tax_total))
        shipping_cost = '${:,.2f}'.format(float(shipping_cost))
        grand_total = '${:,.2f}'.format(float(grand_total))

        payment_method = record.get('custbody_payment_method_for_email')
        if payment_method:
            payment_method = payment_method.replace(' Braintree', '')

        ship_attention = record.get('shippingattention')
        ship_addressee = record.get('shipaddressee')
        ship_name = False
        if ship_attention:
            ship_name = ship_attention
        elif ship_addressee:
            ship_name = ship_addressee

        salesrep = {}
        if record.get('email') and record['email'].lower() not in ['justine@decksdirect.com', 'development@decksdirect.com']:
            repname = record['firstname']
            repemail = record['email']
            salesrep = {
                'RepName': record['firstname'],
                'RepEmail': record['email']
            }

        #Klaviyo CRM has the following special fields you can set for customer_properties
        #$email: string
        #$first_name: string
        #$last_name: string
        #$phone_number: string; eg: "+13239169023"
        #$city: string
        #$region: string; state, or other region
        #$country: string
        #$zip: string
        #$image: string; url to a photo of a person
        #$consent: list of strings; eg: ['sms', 'email', 'web', 'directmail', 'mobile']

        #You can also set the following special fields in event properties with the Track endpoint
        #event_id: a unique identifier for an event
        #$value: a numeric value to associate with this event (e.g. the dollar value of a purchase
        return_obj = {
            'customer_properties': {
                '$email': email,
            },
            'event': 'Placed Order',
            'properties': {
                '$value': grand_total,
                'TaxTotal': tax_total,
                'GrandTotal': grand_total,
                'ShippingCost': shipping_cost,
                'OrderID': sales_order_number,
                'BillingAddress': bill_address,
                'ShippingAddress': ship_address,
                'PaymentMethod': payment_method,
                'ShippingMethod': shipping_method,
                'ShippingName': ship_name,
                'Items': [self.convert_sale_line(record)],
                'SalesRep': salesrep,
            }
        }

        return return_obj


    def convert_sale_line(self, record):
        product_obj = self.env['product']

        qty = record['quantity']
        sku = record['custitem36']
        item_id = record['item']['internalid']

        description = record.get('purchasedescription')
        options = record.get('custcol_custom_options')
        discount_amount = record.get('discountamount')
        if not discount_amount:
            discount_amount = 0
        else:
            discount_amount = round(float(discount_amount), 2)

        subtotal = record.get('amount')
        subtotal = round(float(subtotal), 2)
        options = self.explode_item_options(options)
        return {
            'internalid': item_id,
            'sku': sku,
            'description': description,
            'discount_amount': discount_amount,
            'sale_line_qty': qty,
            'sale_line_amount': subtotal,
            'subtotal': '${:,.2f}'.format(subtotal),
            'options': options
        }
