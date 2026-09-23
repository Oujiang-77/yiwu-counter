"""Local persistence. No network operations are performed in this module."""
from __future__ import annotations
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import uuid
import zipfile
from contextlib import contextmanager, closing
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

VERSION = '0.1.3'
TEXT_FIELDS = ('code','factoryCode','name','factory','size','battery','charger','cat','notes')

def normalize_product(data):
    out=dict(data)
    for key in ('area','inner','min'):out.pop(key,None)
    out['images']=out.get('images', [out['image']] if out.get('image') else [])
    out['boxImages']=out.get('boxImages',[])
    out['image']=out['images'][0] if out['images'] else ''
    return out

def now():
    return datetime.now().isoformat(timespec='seconds')

def validate_product(data):
    out = {k: str(data.get(k) or '').strip() for k in TEXT_FIELDS}
    out['code'] = out['code'].upper()
    for k, label in [('code','销售编码'),('factoryCode','厂家编码'),('name','商品名称')]:
        if not out[k]:
            raise ValueError(f'请填写{label}')
    if any(len(v)>300 for v in out.values()):
        raise ValueError('文字字段最多 300 个字符')
    for k, label in [('pack','装箱数')]:
        if str(data.get(k,'')).strip() == '':
            out[k] = 0
            continue
        try:
            v = Decimal(str(data.get(k,'')))
            if not v.is_finite() or v != v.to_integral_value() or not 0 <= v <= 1000000:
                raise ValueError()
            out[k] = int(v)
        except (InvalidOperation,ValueError):
            raise ValueError(f'{label}须为 0～100 万的整数')
    for k,label,precision in [('price','出厂价','0.01'),('volume','单件体积','0.000001')]:
        if str(data.get(k,'')).strip() == '':
            out[k] = 0.0
            continue
        try:
            v = Decimal(str(data.get(k,'')))
            if not v.is_finite() or v<0 or v>100000000:
                raise ValueError()
            if v != v.quantize(Decimal(precision)):
                raise ValueError()
            out[k] = float(v)
        except (InvalidOperation,ValueError):
            raise ValueError(f'{label}须为非负数，单价最多 2 位、体积最多 6 位小数')
    out['cat'] = out['cat'] or '日用百货'
    for key,label in [('images','主图'),('boxImages','彩盒')]:
        images=data.get(key,([data['image']] if data.get('image') else []) if key=='images' else [])
        if not isinstance(images,list) or len(images)>5:raise ValueError(f'{label}最多上传 5 张图片')
        if any(not isinstance(v,str) or not re.fullmatch(r'[a-f0-9]{32}\.jpg',v) for v in images):raise ValueError('图片引用无效')
        out[key]=list(dict.fromkeys(images))
    out['image']=out['images'][0] if out['images'] else ''
    return out

class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.db = self.root/'counter.sqlite3'
        for folder in ('images','backups','exports','imports'):
            (self.root/folder).mkdir(exist_ok=True)
        self.lock=threading.RLock()
        with self.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS products (
             id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE,
             factory TEXT NOT NULL, factory_code TEXT NOT NULL, data TEXT NOT NULL,
             created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
             UNIQUE(factory,factory_code));
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
             data TEXT NOT NULL, file TEXT NOT NULL);
            PRAGMA user_version=1;
            ''')

    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.db,timeout=20)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            with c:yield c
        finally:c.close()

    def products(self):
        with self.lock, self.connect() as c:
            return [dict(normalize_product(json.loads(r['data'])),id=r['id'],updatedAt=r['updated_at']) for r in c.execute('SELECT * FROM products ORDER BY id DESC')]

    def save_product(self,data,product_id=None):
        p=validate_product(data)
        if any(not (self.root/'images'/name).is_file() for name in p['images']+p['boxImages']):
            raise ValueError('图片不存在，请重新上传')
        with self.lock,self.connect() as c:
            try:
                if product_id:
                    old=c.execute('SELECT id FROM products WHERE id=?',(product_id,)).fetchone()
                    if not old: raise ValueError('商品不存在')
                    c.execute('UPDATE products SET code=?,factory=?,factory_code=?,data=?,updated_at=? WHERE id=?',
                              (p['code'],p['factory'],p['factoryCode'].upper(),json.dumps(p,ensure_ascii=False),now(),product_id))
                else:
                    product_id=c.execute('INSERT INTO products(code,factory,factory_code,data,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                        (p['code'],p['factory'],p['factoryCode'].upper(),json.dumps(p,ensure_ascii=False),now(),now())).lastrowid
            except sqlite3.IntegrityError:
                raise ValueError('销售编码已存在，或同厂家已有该厂家编码，请编辑原商品')
        return dict(p,id=product_id)

    def commit_import(self, rows):
        """All accepted rows are committed in one transaction; duplicates never overwrite."""
        count=0
        with self.lock,self.connect() as c:
            try:
                for row in rows:
                    p=validate_product(row)
                    if any(not (self.root/'images'/name).is_file() for name in p['images']+p['boxImages']):raise ValueError('图片不存在，请重新导入')
                    c.execute('INSERT INTO products(code,factory,factory_code,data,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                        (p['code'],p['factory'],p['factoryCode'].upper(),json.dumps(p,ensure_ascii=False),now(),now()))
                    count+=1
            except sqlite3.IntegrityError:
                raise ValueError('提交时发现重复编码，本批次未写入；请重新预览')
        return count

    def get_value(self,key,default=None):
        with self.lock,self.connect() as c:
            r=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
            return json.loads(r['value']) if r else default

    def set_value(self,key,value):
        with self.lock,self.connect() as c:
            c.execute('INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)',(key,json.dumps(value,ensure_ascii=False)))

    def order_items(self, items):
        if not items: raise ValueError('请先选择商品')
        by_id={p['id']:p for p in self.products()}
        grouped={}
        for row in items:
            try:
                pid=int(row['id']); q=Decimal(str(row['quantity']))
                if not q.is_finite() or q!=q.to_integral_value() or not 1<=q<=1000000:raise ValueError()
            except (KeyError,ValueError,TypeError,InvalidOperation):
                raise ValueError('订货件数须为正整数，最多 100 万件')
            if pid not in by_id:raise ValueError('商品已不存在，请刷新后重试')
            grouped[pid]=grouped.get(pid,0)+int(q)
        result=[]
        for pid,q in grouped.items():
            p=by_id[pid]
            if q>1000000:raise ValueError(f"{p['code']}：最多 100 万件")
            units=q*p['pack']
            amount=(Decimal(str(p['price']))*units).quantize(Decimal('.01'))
            result.append(dict(p,quantity=q,units=units,amount=str(amount),totalVolume=str(Decimal(str(p['volume']))*q)))
        return result

    def save_order(self,order_id,items,file):
        with self.lock,self.connect() as c:
            c.execute('INSERT INTO orders(id,created_at,data,file) VALUES(?,?,?,?)',(order_id,now(),json.dumps(items,ensure_ascii=False),file))

    def orders(self):
        with self.lock,self.connect() as c:
            return [dict(id=r['id'],createdAt=r['created_at'],file=r['file'],items=json.loads(r['data'])) for r in c.execute('SELECT * FROM orders ORDER BY created_at DESC LIMIT 100')]

    def backup(self,reason='manual'):
        name=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+reason+'-'+uuid.uuid4().hex[:6]+'.zip'
        target=self.root/'backups'/name
        with self.lock,tempfile.TemporaryDirectory(dir=self.root) as folder:
            db=Path(folder)/'counter.sqlite3'
            with self.connect() as source,closing(sqlite3.connect(db)) as dest:source.backup(dest)
            files=[('counter.sqlite3',db)]+[('images/'+p.name,p) for p in (self.root/'images').glob('*.jpg')]
            manifest={'schema':1,'version':VERSION,'createdAt':now(),'files':{n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in files}}
            with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
                for n,p in files:z.write(p,n)
                z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
        return name

    def backups(self):
        return [dict(name=p.name,size=p.stat().st_size) for p in sorted((self.root/'backups').glob('*.zip'),reverse=True)]

    def restore(self,name):
        if not re.fullmatch(r'[\w.-]+\.zip',name):raise ValueError('备份文件名无效')
        src=self.root/'backups'/name
        if not src.is_file():raise ValueError('备份不存在')
        with self.lock,tempfile.TemporaryDirectory(dir=self.root) as folder:
            tmp=Path(folder)
            with zipfile.ZipFile(src) as z:
                if sum(i.file_size for i in z.infolist())>2*1024**3:raise ValueError('备份过大')
                if len(z.namelist())!=len(set(z.namelist())):raise ValueError('备份包含重复文件')
                manifest=json.loads(z.read('manifest.json'))
                if manifest.get('schema')!=1:raise ValueError('不支持的备份版本')
                for n,h in manifest['files'].items():
                    if n!='counter.sqlite3' and not re.fullmatch(r'images/[a-f0-9]{32}\.jpg',n):raise ValueError('备份文件路径无效')
                    data=z.read(n)
                    if hashlib.sha256(data).hexdigest()!=h:raise ValueError('备份校验失败')
                    p=tmp/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            with closing(sqlite3.connect(tmp/'counter.sqlite3')) as c:
                if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('备份数据库损坏')
                if c.execute('PRAGMA user_version').fetchone()[0]!=1:raise ValueError('数据库版本不兼容')
                c.execute('SELECT data FROM products LIMIT 1')
                for (raw,) in c.execute('SELECT data FROM products'):
                    p=normalize_product(json.loads(raw))
                    if any(not (tmp/'images'/name).is_file() for name in p['images']+p['boxImages']):raise ValueError('备份缺少商品图片')
            safe=self.backup('before-restore')
            # Copy image assets before atomically swapping the database. Extra images are harmless.
            for p in (tmp/'images').glob('*.jpg'):shutil.copy2(p,self.root/'images'/p.name)
            os.replace(tmp/'counter.sqlite3',self.db)
        return safe

    def daily_backup(self):
        day=datetime.now().strftime('%Y-%m-%d')
        if self.get_value('lastBackupDay')!=day:
            self.backup('daily');self.set_value('lastBackupDay',day)
