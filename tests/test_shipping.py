import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from app.shipping import quote_shipping, money


class ShippingTests(unittest.TestCase):
    def test_below_boundary(self):
        r = quote_shipping(49999, 'metro_campo_grande')
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['shipping_cents'], 3500)
        self.assertEqual(r['grand_total_cents'], 53499)
        self.assertEqual(r['grand_total_brl'], '534.99')

    def test_exact_boundary_requires_confirmation(self):
        r = quote_shipping(50000, 'metro_campo_grande')
        self.assertEqual(r['status'], 'needs_confirmation')
        self.assertEqual(r['reason'], 'shipping_exactly_500')
        self.assertIsNone(r['shipping_cents'])
        self.assertIsNone(r['grand_total_cents'])

    def test_above_boundary_is_free(self):
        r = quote_shipping(50001, 'metro_campo_grande')
        self.assertEqual(r['shipping_cents'], 0)
        self.assertEqual(r['shipping_brl'], '0.00')
        self.assertEqual(r['grand_total_brl'], '500.01')
        self.assertEqual(r['delivery_business_days'], {'min':1, 'max':3})

    def test_missing_order_total(self):
        r = quote_shipping(region='metro_campo_grande')
        self.assertEqual(r['status'], 'needs_information')
        self.assertEqual(r['reason'], 'order_total_required')
        self.assertIsNone(r['shipping_cents'])

    def test_region_is_not_inferred(self):
        r = quote_shipping(60000)
        self.assertEqual(r['status'], 'needs_information')
        self.assertEqual(r['reason'], 'destination_region_required')
        self.assertIsNone(r['shipping_cents'])

    def test_outside_region_never_has_invented_price(self):
        for amount in (None, 10000, 60000):
            with self.subTest(amount=amount):
                r = quote_shipping(amount, 'other_city')
                self.assertEqual(r['status'], 'requires_quote')
                self.assertIsNone(r['shipping_cents'])
                self.assertIsNone(r['grand_total_cents'])
                self.assertFalse(r['carrier_api_called'])
                self.assertIn('destination_postal_code',r['required_for_quote'])

    def test_large_instruments(self):
        for size in (True, None):
            self.assertIn('special_shipping_note', quote_shipping(60000,'other_city',size))
        self.assertNotIn('special_shipping_note', quote_shipping(60000,'other_city',False))

    def test_invalid_input(self):
        for amount in (True, 0, -1, 3.5, '60000'):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                quote_shipping(amount, 'metro_campo_grande')
        for region in ('sp', True, [], None):
            with self.subTest(region=region), self.assertRaises(ValueError):
                quote_shipping(60000,region)
        with self.assertRaises(ValueError):
            quote_shipping(60000, 'other_city', 'false')

    def test_decimal_formatting_without_float_loss(self):
        self.assertEqual(money(100000000000000001),'1000000000000000.01')
        self.assertEqual(quote_shipping(1,'metro_campo_grande')['order_total_brl'],'0.01')

    def test_cli_success(self):
        r = subprocess.run([sys.executable, 'app/shipping.py', '--region', 'metro_campo_grande', '--order-total','600'],
                           cwd=PROJECT_ROOT,capture_output=True,text=True,encoding='utf-8',env={**os.environ, 'PYTHONIOENCODING':'utf-8'})
        self.assertEqual(r.returncode,0,r.stderr)
        result = json.loads(r.stdout)
        self.assertEqual(result['shipping_cents'],0)
        self.assertEqual(result['grand_total_brl'],'600.00')

    def test_cli_confirmation_not_success_or_free_shipping(self):
        r = subprocess.run([sys.executable, 'app/shipping.py', '--region', 'metro_campo_grande', '--order-total','500,00'],
                           cwd=PROJECT_ROOT,capture_output=True,text=True,encoding='utf-8',env={**os.environ, 'PYTHONIOENCODING':'utf-8'})
        self.assertEqual(r.returncode,2,r.stderr)
        self.assertEqual(json.loads(r.stdout)['status'],'needs_confirmation')


if __name__ == '__main__':
    unittest.main(verbosity=2)
