import asyncio, os, xmlrpc.client
from dotenv import load_dotenv
load_dotenv('../.env')

class MockConn:
    def __init__(self):
        self.db = os.getenv('ODOO_DB')
        self.uid = 33831
        self.api_key = os.getenv('ODOO_API_KEY')
        self._m = xmlrpc.client.ServerProxy(os.getenv('ODOO_URL') + '/xmlrpc/2/object')
    def execute_kw(self, model, method, args, kwargs=None):
        return self._m.execute_kw(self.db, self.uid, self.api_key, model, method, args, kwargs or {})

class MockApp:
    def tool(self, *a, **k):
        def d(f): return f
        return d

from mcp_server_odoo.csa_tools import CSAToolHandler
h = CSAToolHandler(MockApp(), MockConn())
r = asyncio.run(h._handle_get_bom_with_stock('SMH-150D'))

if not r['found']:
    print('Not found:', r['message'])
else:
    print('Product:', r['finished_product'])
    print('Components:', r['total_components'])
    print('Has shortages:', r['has_shortages'])
    print('Shortage count:', r['shortage_count'])
    for c in r['components']:
        status = 'SHORTAGE' if c['shortage'] else 'OK'
        print(f"  {c['product_name'][:60]} | need={c['qty_needed']} have={c['qty_available']} [{status}]")