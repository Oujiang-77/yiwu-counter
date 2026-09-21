import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from openpyxl import Workbook
from sheets import inspect_book, preview_import
from storage import Store

class ImportTests(unittest.TestCase):
    def test_empty_mapping_and_cached_images(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);p=Path(folder)/'fixture.xlsx'
            w=Workbook();s=w.active
            s.append(['销售编码','厂家编码','商品名称','厂家名称','装箱数','出厂价'])
            s.append(['A-01','001','风扇','测试厂',12,3.5]);w.save(p)
            cache={};config={'sheet':'Sheet'}
            self.assertEqual(preview_import(store,p,config,cache)['valid'],1)
            with patch('sheets.read_sheet',side_effect=AssertionError('must reuse parsed data')):
                result=preview_import(store,p,dict(config,mapping={}),cache)
            self.assertEqual(result['mapping'],{})
            self.assertEqual(result['valid'],0)

    def test_non_media_expansion_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'large.xlsx'
            with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
                with z.open('xl/worksheets/sheet1.xml','w') as target:
                    for _ in range(201):target.write(b' '*1024**2)
            with self.assertRaisesRegex(ValueError,'200 MB'):inspect_book(p)

    def test_optional_factory_pack_and_price(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            data={'code':'A-01','factoryCode':'001','name':'空值商品','factory':'','pack':'','price':'','volume':'','cat':'日用百货'}
            from storage import validate_product
            saved=validate_product(data)
            self.assertEqual(saved['factory'],'')
            self.assertEqual(saved['pack'],0)
            self.assertEqual(saved['price'],0.0)
            book=Path(folder)/'optional.xlsx'
            w=Workbook();s=w.active
            s.append(['销售编码','厂家编码','商品名称','厂家名称','装箱数','出厂价'])
            s.append(['A-02','002','导入空值商品','','',''])
            w.save(book)
            result=preview_import(store,book,{'sheet':'Sheet'})
            self.assertEqual(result['valid'],1)
            self.assertEqual(result['rows'][0]['data']['pack'],0)
            self.assertEqual(result['rows'][0]['data']['price'],0.0)

if __name__=='__main__':unittest.main()
