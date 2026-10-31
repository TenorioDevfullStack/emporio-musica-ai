import json
import sqlite3
import sys
import unittest
from copy import deepcopy
from contextlib import closing
from functools import partial
from tempfile import TemporaryDirectory
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from app import agent
from app.import_data import TABLES, MONEY_COLUMNS, read_table, DATA_DIR
from groq.types.chat import ChatCompletion
from app.catalog import search_products as real_search_products
from app.pricing import search_offers as real_search_offers, quote_product as real_quote_product


def completion(calls=None, text='Resposta simulada.', reason=None):
    return ChatCompletion.model_validate({
        'id': 'test', 'object': 'chat.completion', 'created': 0, 'model': agent.MODEL,
        'choices': [{'index': 0, 'finish_reason': reason or ('tool_calls' if calls else 'stop'),
                     'message': {'role': 'assistant', 'content': None if calls else text,
                                 'tool_calls': calls}}],
        'usage': {'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30}})


def call(name, args, ident='call1'):
    return {'id': ident, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.requests.append(deepcopy(kwargs))
        return next(self.responses)


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Os testes usam banco temporario e nao alteram data/store.sqlite3.
        temp_dir = TemporaryDirectory()
        cls.addClassCleanup(temp_dir.cleanup)
        database_path = Path(temp_dir.name) / 'test.sqlite3'
        with closing(sqlite3.connect(database_path)) as conn, conn:
            for table in ('categories', 'products', 'promotions'):
                spec = TABLES[table]
                conn.execute(f'CREATE TABLE IF NOT EXISTS {table} ({spec["schema"]})')
                cols = [MONEY_COLUMNS.get(c,c) for c in spec['columns']]
                rows = read_table(DATA_DIR, table, spec)
                conn.executemany(f'INSERT OR REPLACE INTO {table} ({",".join(cols)}) VALUES ({",".join("?" for _ in cols)})', rows)
        for name, function in (
            ('search_offers', real_search_offers),
            ('search_products', real_search_products),
            ('quote_product', real_quote_product),
        ):
            patcher = patch.object(agent, name, new=partial(function, database_path=database_path))
            patcher.start()
            cls.addClassCleanup(patcher.stop)


    def test_real_price(self):
        r = agent.execute_tool('search_offers', '{"query":"Ohana CK-20","max_price_cents":50000}')
        self.assertEqual(r['items'][0]['product_id'], 121)
        self.assertEqual(r['items'][0]['final_price_cents'], 43920)
        pix = agent.execute_tool('quote_product', '{"product_id":121,"payment_method":"pix"}')
        self.assertEqual(pix['final_price_cents'], 43920)
        self.assertFalse(pix['pix_discount_applied'])

    def test_real_policy(self):
        r = agent.execute_tool('search_policies', '{"query":"posso devolver uma compra online?"}')
        self.assertEqual(r['status'], 'context_found')
        self.assertEqual(r['matches'][0]['section_id'], '4.1')
        self.assertEqual(r['matches'][0]['pages'], [4])
        self.assertIn('4.4', [x['section_id'] for x in r['related_context']])

    def test_invalid(self):
        for name,args in [('search_offers', '{'), ('execute_code', '{}'), ('search_offers','[]'),
                          ('quote_product','{"product_id":true}'),
                          ('search_offers','{"database_path":"secret"}'),
                          ('search_offers','{"limit":50}'), ('search_offers','{"payment_method":"cash"}')]:
            with self.subTest(name=name,args=args):
                self.assertEqual(agent.execute_tool(name,args)['status'], 'invalid_arguments')

    def test_loop_and_protocol(self):
        client = Client([completion([call('search_offers', {'query':'Ohana CK-20','max_price_cents':50000})]), completion()])
        r = agent.run_agent('Ohana CK-20 ate 500 reais', client)
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['api_calls'], 2)
        self.assertEqual(r['usage']['total_tokens'], 60)
        self.assertEqual(r['tools_used'][0]['name'], 'search_offers')
        self.assertIn({'data_source':'provided_snapshot','product_id':121}, r['sources'])
        msg = client.requests[1]['messages'][-1]
        self.assertEqual(msg['tool_call_id'],'call1')
        self.assertEqual(json.loads(msg['content'])['items'][0]['final_price_cents'],43920)
        self.assertNotIn('reasoning', client.requests[1]['messages'][-2])

    def test_multiple_tools(self):
        client = Client([completion([call('quote_product', {'product_id':121}),
                                     call('search_policies', {'query':'devolucao online'}, 'call2')]), completion()])
        r = agent.run_agent('Preco e devolucao',client)
        self.assertEqual(len(r['tools_used']),2)
        self.assertIn({'document':'políticas_da_loja.pdf','section':'4.1','pages':[4]},r['sources'])

    def test_tool_error(self):
        with patch.object(agent, 'search_offers', side_effect=sqlite3.OperationalError('private secret')):
            r = agent.execute_tool('search_offers','{}')
        self.assertEqual(r['status'],'tool_error')
        self.assertNotIn('private',json.dumps(r))

    def test_installment_guard_uses_pdf_not_generation(self):
        # A segunda resposta maliciosa jamais deve ser consumida.
        client = Client([completion([call('search_policies', {'query':'parcelamento compra de 600 em 12 vezes'})]),
                         completion(text='Conflito inventado: o manual aprova 12x de 50')])
        r = agent.run_agent('Posso parcelar 600 em 12 vezes?',client)
        self.assertEqual(r['status'],'needs_confirmation')
        self.assertEqual(r['response_origin'],'policy_guard')
        self.assertEqual(len(client.requests),1)
        self.assertEqual(r['api_calls'],1)
        self.assertEqual(r['usage']['total_tokens'],30)
        self.assertNotIn('installment_conflict',r['response'])
        self.assertNotIn('Conflito inventado',r['response'])
        self.assertIn('4x a 6x: sem juros, parcela mínima de R$ 80,00',r['response'])
        self.assertIn('7x a 12x: sem juros, parcela mínima de R$ 100,00',r['response'])
        self.assertIn('Confirme com a equipe',r['response'])
        self.assertIn('seção 3.1',r['response'])

    def test_other_ambiguities_do_not_trigger_installment_guard(self):
        self.assertIsNone(agent.installment_review({'ambiguities':[{'code':'contact_conflict'}]}))
        self.assertIsNone(agent.installment_review({'ambiguities':[]}))

    def test_missing_sections_still_does_not_invent(self):
        message = agent.installment_review({'ambiguities':[{'code':'installment_conflict'}]})
        self.assertIn('Confirme com a equipe',message)
        self.assertNotIn('R$',message)

    def test_shipping_normal_result_and_source(self):
        for amount, fee in ((60000,0),(40000,3500)):
            with self.subTest(amount=amount):
                client = Client([completion([call('quote_shipping', {'region':'metro_campo_grande','order_total_cents':amount})]),
                                 completion(text='O manual considera o valor sem descontos. Frete garantido.')])
                r = agent.run_agent('Qual o frete do meu pedido?',client)
                self.assertEqual(r['status'],'ok')
                self.assertEqual(len(client.requests),1)
                self.assertEqual(r['tools_used'][0]['name'],'quote_shipping')
                self.assertEqual(r['shipping_quotes'][0]['shipping_cents'],fee)
                self.assertEqual(r['shipping_quotes'][0]['grand_total_cents'],amount+fee)
                self.assertIn({'document':'políticas_da_loja.pdf','sections':['5.1'],'pages':[4]},r['sources'])
                self.assertEqual(r['response_origin'],'shipping_guard')
                self.assertIn('O manual não especifica',r['response'])
                self.assertIn('antes ou depois dos descontos',r['response'])
                self.assertNotIn('manual considera',r['response'])
                self.assertNotIn('garantido',r['response'])
                self.assertIn('5.1',r['response'])
                self.assertIn('0,00' if fee == 0 else '35,00',r['response'])
                self.assertIn('600,00' if fee == 0 else '435,00',r['response'])

    def test_shipping_exact_boundary_blocks_fabricated_zero(self):
        client = Client([completion([call('quote_shipping', {'region':'metro_campo_grande','order_total_cents':50000})]),
                         completion(text='Frete gratis garantido')])
        r = agent.run_agent('Pedido de 500 para regiao local',client)
        self.assertEqual(len(client.requests),1)
        self.assertEqual(r['status'],'needs_confirmation')
        self.assertEqual(r['response_origin'],'shipping_guard')
        self.assertIsNone(r['shipping_quotes'][0]['shipping_cents'])
        self.assertIn('Confirme',r['response'])
        self.assertIn('5.1',r['response'])
        self.assertNotIn('garantido',r['response'])

    def test_shipping_unknown_region(self):
        client = Client([completion([call('quote_shipping', {'order_total_cents':60000})])])
        r = agent.run_agent('Pedido de 600 qual o frete?',client)
        self.assertEqual(r['status'],'needs_information')
        self.assertIn('regiao',r['response'])
        self.assertEqual(r['api_calls'],1)

    def test_shipping_missing_amount(self):
        client = Client([completion([call('quote_shipping', {'region':'metro_campo_grande'})])])
        r = agent.run_agent('Frete local?',client)
        self.assertEqual(r['status'],'needs_information')
        self.assertIn('valor do pedido',r['response'])
        self.assertIsNone(r['shipping_quotes'][0]['grand_total_cents'])

    def test_shipping_other_city_requires_quote(self):
        client = Client([completion([call('quote_shipping', {'region':'other_city','order_total_cents':60000})])])
        r = agent.run_agent('Frete para Sao Paulo?',client)
        self.assertEqual(r['status'],'requires_quote')
        self.assertEqual(r['response_origin'],'shipping_guard')
        self.assertIn('CEP',r['response'])
        self.assertIn('cotacao individual',r['response'])
        self.assertIsNone(r['shipping_quotes'][0]['shipping_cents'])
        self.assertFalse(r['shipping_quotes'][0]['carrier_api_called'])

    def test_shipping_validates_model_arguments(self):
        for args in ({'region':'SP'},{'order_total_cents':True},{'order_total_cents':0}, {'cep':'00000000'}):
            with self.subTest(args=args):
                self.assertEqual(agent.execute_tool('quote_shipping',json.dumps(args))['status'],'invalid_arguments')

    def test_shipping_error_is_not_a_free_quote(self):
        with patch.object(agent,'quote_shipping',side_effect=ValueError('private path')):
            r = agent.execute_tool('quote_shipping','{}')
        self.assertEqual(r['status'],'tool_error')
        self.assertIsNone(agent.shipping_review(r))
        self.assertNotIn('private',r['message'])

    def test_limits(self):
        client = Client([completion([call('quote_product', {'product_id':121}, str(n)) for n in range(10)]), completion()])
        r = agent.run_agent('Consultar',client)
        self.assertEqual(sum(t['status']=='tool_limit' for t in r['tools_used']),2)
        self.assertEqual(client.requests[-1]['tool_choice'],'none')
        client = Client([completion([call('quote_product', {'product_id':121})]) for _ in range(5)])
        r = agent.run_agent('Consultar',client)
        self.assertEqual(r['status'],'step_limit')
        self.assertEqual(len(client.requests),5)
        self.assertEqual(client.requests[-1]['tool_choice'],'none')

    def test_incomplete_and_no_tools(self):
        r = agent.run_agent('Oi', Client([completion([call('scope_response', {'intent':'greeting'})])]))
        self.assertEqual(r['status'],'ok')
        self.assertEqual(r['tools_used'][0]['name'],'scope_response')
        self.assertIn('Empório da Música',r['response'])
        r = agent.run_agent('Oi', Client([completion(reason='length')]))
        self.assertEqual(r['status'],'incomplete_response')

    def test_out_of_scope_redirect_does_not_generate_recipe(self):
        client = Client([completion([call('scope_response', {'intent':'out_of_scope'})]),
                         completion(text='Ingredientes: farinha, chocolate')])
        r = agent.run_agent('Me ensine uma receita de bolo de chocolate.',client)
        self.assertEqual(r['status'],'out_of_scope')
        self.assertEqual(r['response_origin'],'scope_guard')
        self.assertEqual(len(client.requests),1)
        self.assertIn('Empório da Música',r['response'])
        self.assertNotIn('Ingredientes',r['response'])
        self.assertEqual(r['sources'],[])

    def test_ungrounded_free_response_is_not_delivered(self):
        client = Client([completion(text='Ingredientes: farinha, chocolate. Modo de preparo...')])
        r = agent.run_agent('Me ensine uma receita de bolo de chocolate.',client)
        self.assertEqual(r['status'],'needs_information')
        self.assertEqual(r['response_origin'],'scope_guard')
        self.assertNotIn('Ingredientes',r['response'])
        self.assertNotIn('preparo',r['response'])
        self.assertIn('loja',r['response'])

    def test_clarification_and_invalid_scope_intent(self):
        client = Client([completion([call('scope_response', {'intent':'clarification'})])])
        r = agent.run_agent('Quero comprar.',client)
        self.assertEqual(r['status'],'needs_information')
        self.assertIn('produto',r['response'])
        self.assertEqual(agent.execute_tool('scope_response','{"intent":"recipe"}')['status'],'invalid_arguments')
        self.assertEqual(agent.execute_tool('scope_response','{"intent":"out_of_scope","message":"Ingredientes..."}')['status'],'invalid_arguments')
        r = agent.run_agent('Oi', Client([completion(text='')]))
        self.assertEqual(r['status'],'incomplete_response')


if __name__ == '__main__':
    unittest.main(verbosity=2)
