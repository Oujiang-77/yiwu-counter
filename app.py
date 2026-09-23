from __future__ import annotations
import argparse
import io
import json
import logging
import os
import secrets
import socket
import shutil
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path
import uvicorn
from fastapi import FastAPI,File,UploadFile,Request,HTTPException
from fastapi.responses import FileResponse,JSONResponse,RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from storage import Store,VERSION
from sheets import FIELDS,MAX_IMPORT_BYTES,inspect_book,read_sheet,guess_mapping,preview_import,save_image,template_bytes,export_bytes
import recognition
from update import check_for_update,run_update_helper
from quotation import EXPORT_FIELDS,validate_columns

DEFAULT_DATA_DIR_NAME = 'HuoYouShu'
APP_MUTEX_NAME = r'Local\HuoYouShu-Counter'

def should_reuse_running_instance(health):
    if health.get('application') != 'yiwu-counter':
        return False
    if health.get('version') != VERSION:
        raise RuntimeError('旧版档口开单系统仍在运行。请先在旧版页面点击“退出系统”，或在任务管理器结束旧程序，再打开新版桌面图标。')
    return True

def default_data_dir():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / DEFAULT_DATA_DIR_NAME

def choose_data_folder():
    """Kept for command-line compatibility; the browser now selects folders itself."""
    return None

def resolve_data_dir(explicit=None):
    """Resolve the persistent data directory without blocking the local server.

    On a brand-new installation the app temporarily uses the default local
    directory.  The UI then opens its in-app folder browser and lets the user
    choose the real location.  This keeps first launch usable even when the
    packaged process has no desktop UI access.
    """
    if explicit:
        return Path(explicit)
    default = default_data_dir()
    marker = default / 'data-location.json'
    if marker.exists():
        try:
            selected = Path(json.loads(marker.read_text('utf8')).get('path','')).expanduser()
            if selected:
                try:
                    selected.mkdir(parents=True,exist_ok=True)
                    return selected
                except OSError:
                    pass
        except (OSError,ValueError,TypeError):
            pass
    if (default / 'counter.sqlite3').exists():
        return default
    return default

def copy_data_dir(source, target):
    source = Path(source).resolve()
    target = Path(target).resolve()
    if source == target:
        return
    if source in target.parents or target in source.parents:
        raise ValueError('新存储位置不能放在当前数据目录里面或包含当前数据目录')
    target.mkdir(parents=True,exist_ok=True)
    if any(target.iterdir()):
        raise ValueError('请选择空文件夹作为新的存储位置')
    for item in source.iterdir():
        if item.name in ('runtime.json','app.log','data-location.json'):
            continue
        destination = target / item.name
        if item.is_dir():
            shutil.copytree(item,destination)
        else:
            shutil.copy2(item,destination)

def make_app(data_dir,token=None,needs_data_location=False):
    store=Store(data_dir);token=token or secrets.token_urlsafe(32)
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    app.state.store=store;app.state.token=token;app.state.previews={};app.state.needs_data_location=needs_data_location
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
    web=root/'web'

    @app.middleware('http')
    async def local_access(req,call_next):
        host=req.headers.get('host','').split(':')[0]
        if host not in ('127.0.0.1','localhost'):
            return JSONResponse({'detail':'仅允许本机访问'},status_code=403)
        origin=req.headers.get('origin')
        if origin and origin not in (f'http://{req.headers.get("host")}',):
            return JSONResponse({'detail':'访问来源无效'},status_code=403)
        public=req.url.path in ('/health','/') or req.url.path.startswith('/assets/')
        if not public and not secrets.compare_digest(req.cookies.get('counter_session',''),token):
            return JSONResponse({'detail':'会话失效，请重新双击程序打开'},status_code=401)
        if req.method in ('POST','PUT','DELETE') and req.headers.get('x-counter-request')!='1':
            return JSONResponse({'detail':'请求校验失败'},status_code=403)
        try:result=await call_next(req)
        except Exception:
            logging.exception('Unhandled request failure')
            return JSONResponse({'detail':'操作失败，请重试或查看本地日志'},status_code=500)
        result.headers['X-Content-Type-Options']='nosniff'
        result.headers['Cache-Control']='no-store'
        result.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
        return result

    @app.exception_handler(ValueError)
    async def invalid(req,exc):return JSONResponse({'detail':str(exc)},status_code=400)

    @app.get('/health')
    def health():return {'application':'yiwu-counter','version':VERSION}

    @app.get('/')
    def index(request:Request,session:str=''):
        if session and secrets.compare_digest(session,token):
            r=RedirectResponse('/',status_code=303);r.set_cookie('counter_session',token,httponly=True,samesite='strict');return r
        if not secrets.compare_digest(request.cookies.get('counter_session',''),token):
            raise HTTPException(401,'请从“档口开单系统.exe”重新打开，当前浏览器没有本机会话。')
        return FileResponse(web/'index.html')

    app.mount('/assets',StaticFiles(directory=web),name='assets')

    @app.get('/api/state')
    def state():
        saved_columns=store.get_value('exportColumns',list(EXPORT_FIELDS))
        try: saved_columns=validate_columns(saved_columns)
        except ValueError: saved_columns=list(EXPORT_FIELDS)
        return {'products':store.products(),'draft':store.get_value('draft',{'selected':[],'quantities':{}}),'version':VERSION,'dataDir':str(store.root),'exportFields':EXPORT_FIELDS,'exportColumns':saved_columns,'ocrAvailable':recognition.available(),'needsDataLocation':bool(app.state.needs_data_location)}

    @app.get('/api/update/check')
    def update_check():
        return check_for_update(VERSION)

    @app.post('/api/update/apply')
    def update_apply():
        """Start the detached updater; the running server exits shortly after."""
        if not getattr(sys, 'frozen', False):
            raise ValueError('开发模式不支持自动替换，请使用正式安装版')
        info = check_for_update(VERSION, timeout=15)
        if info.get('status') != 'ok' or not info.get('updateAvailable'):
            raise ValueError('当前没有可用的新版本')
        package = info.get('package') or {}
        package_url = str(package.get('url') or '')
        checksum_url = str(package.get('checksumUrl') or '')
        if not package_url or not checksum_url:
            raise ValueError('线上发布缺少更新包或 SHA256 校验文件')
        import subprocess
        import tempfile
        helper_dir = Path(tempfile.mkdtemp(prefix='huoyoushu-update-helper-'))
        helper = helper_dir / 'update-helper.exe'
        try:
            shutil.copy2(Path(sys.executable), helper)
            flags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
            subprocess.Popen([
                str(helper), '--apply-update',
                '--update-package-url', package_url,
                '--update-checksum-url', checksum_url,
                '--update-target-dir', str(Path(sys.executable).resolve().parent),
                '--update-pid', str(os.getpid()),
            ], cwd=str(helper_dir), close_fds=True, creationflags=flags)
        except Exception:
            shutil.rmtree(helper_dir, ignore_errors=True)
            raise ValueError('无法启动更新助手，请稍后重试')
        if getattr(app.state, 'server', None):
            threading.Timer(.6, lambda: setattr(app.state.server, 'should_exit', True)).start()
        return {'status': 'started', 'latestVersion': info.get('latestVersion')}

    def switch_data_location(target):
        nonlocal store
        target=Path(target).expanduser()
        if not target.is_absolute():raise ValueError('请输入完整的文件夹路径')
        if target.resolve()==store.root.resolve():
            if app.state.needs_data_location:
                marker=default_data_dir()/'data-location.json'
                try:
                    marker.parent.mkdir(parents=True,exist_ok=True)
                    marker.write_text(json.dumps({'path':str(target)},ensure_ascii=False),encoding='utf8')
                except OSError:
                    logging.exception('无法更新数据目录记忆文件')
            app.state.needs_data_location=False
            return {'cancelled':False,'dataDir':str(store.root)}
        with store.lock:
            copy_data_dir(store.root,target)
            marker=default_data_dir()/'data-location.json'
            try:
                marker.parent.mkdir(parents=True,exist_ok=True)
                marker.write_text(json.dumps({'path':str(target)},ensure_ascii=False),encoding='utf8')
            except OSError:
                logging.exception('无法更新数据目录记忆文件')
            store=Store(target)
            app.state.store=store
            app.state.needs_data_location=False
        return {'cancelled':False,'dataDir':str(store.root)}

    @app.post('/api/data-location/select')
    def select_data_location():
        selected=choose_data_folder()
        if not selected:return {'cancelled':True,'dataDir':str(store.root)}
        return switch_data_location(selected)

    def _folder_path(value):
        """Return a safe absolute directory path for the local browser API."""
        if value is None or not str(value).strip():
            return None
        raw = str(value).strip().strip('"')
        path = Path(raw).expanduser()
        if not path.is_absolute():
            raise ValueError('请选择有效的文件夹')
        try:
            return path.resolve()
        except OSError:
            return path.absolute()

    def _folder_entry(path):
        return {'name':path.name or str(path), 'path':str(path)}

    def _folder_listing(value=None):
        path = _folder_path(value)
        if path is None:
            roots=[]
            if os.name == 'nt':
                for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
                    drive=Path(f'{letter}:\\')
                    if drive.exists(): roots.append(_folder_entry(drive))
            else:
                roots=[_folder_entry(Path('/'))]
            profile=Path(os.environ.get('USERPROFILE',str(Path.home())))
            shortcuts=[]
            for label, candidate in (
                ('桌面',profile/'Desktop'),
                ('文档',profile/'Documents'),
                ('下载',profile/'Downloads'),
            ):
                if candidate.is_dir(): shortcuts.append({'name':label,'path':str(candidate.resolve())})
            return {'path':'','parent':None,'roots':roots,'shortcuts':shortcuts,'entries':[]}
        if not path.exists():
            raise ValueError('文件夹不存在，请重新选择')
        if not path.is_dir():
            raise ValueError('请选择文件夹而不是文件')
        try:
            children=sorted((p for p in path.iterdir() if p.is_dir()), key=lambda p:p.name.casefold())
        except OSError:
            raise ValueError('无法读取该文件夹，请选择其他位置')
        parent=str(path.parent) if path.parent != path else None
        return {'path':str(path),'parent':parent,'roots':[],'shortcuts':[],
                'entries':[_folder_entry(child) for child in children]}

    @app.get('/api/data-location/browse')
    def browse_data_location(path:str=''):
        return _folder_listing(path)

    @app.post('/api/data-location/create-folder')
    def create_data_location_folder(data:dict):
        parent=_folder_path(data.get('parent') if isinstance(data,dict) else None)
        name=data.get('name') if isinstance(data,dict) else None
        if parent is None:
            raise ValueError('请先打开一个文件夹')
        if not isinstance(name,str) or not name.strip():
            raise ValueError('请输入文件夹名称')
        name=name.strip()
        if name in ('.','..') or any(ch in name for ch in '<>:"/\\|?*'):
            raise ValueError('文件夹名称不能包含 \\< > : " / \\ | ? *')
        if len(name)>80:
            raise ValueError('文件夹名称不能超过 80 个字符')
        target=(parent/name).resolve()
        if target.parent != parent.resolve():
            raise ValueError('文件夹名称无效')
        try:
            target.mkdir()
        except FileExistsError:
            raise ValueError('该文件夹已经存在')
        except OSError:
            raise ValueError('无法创建文件夹，请检查权限')
        return _folder_listing(str(parent))

    @app.post('/api/data-location/set')
    def set_data_location(data:dict):
        path=data.get('path') if isinstance(data,dict) else None
        if not isinstance(path,str) or not path.strip():raise ValueError('请输入文件夹路径')
        return switch_data_location(path.strip())

    @app.post('/api/products')
    def create(data:dict):return store.save_product(data)

    @app.put('/api/products/{pid}')
    def edit(pid:int,data:dict):return store.save_product(data,pid)

    @app.put('/api/draft')
    def draft(data:dict):
        ids={p['id'] for p in store.products()}
        selected=[]
        for v in data.get('selected',[]):
            if not isinstance(v,int):raise ValueError('草稿商品编号无效')
            if v in ids and v not in selected:selected.append(v)
        quantities=data.get('quantities',{})
        if not isinstance(quantities,dict) or len(quantities)>10000:raise ValueError('草稿格式无效')
        safe={str(pid):quantities.get(str(pid)) for pid in selected if isinstance(quantities.get(str(pid)),(int,float))}
        store.set_value('draft',{'selected':selected,'quantities':safe});return {'ok':True}

    async def upload_bytes(file,max_bytes=15*1024**2):
        raw=await file.read(max_bytes+1)
        if len(raw)>max_bytes:raise ValueError('文件超过允许大小')
        return raw

    @app.post('/api/images')
    async def upload_image(file:UploadFile=File(...)):
        raw=await upload_bytes(file)
        try:name=save_image(raw,store)
        except (Image.DecompressionBombError,OSError):raise ValueError('无法读取图片，请使用 JPG / PNG / WEBP')
        return {'image':name}

    @app.get('/api/images/{name}')
    def image(name:str):
        import re
        if not re.fullmatch(r'[a-f0-9]{32}\.jpg',name):raise HTTPException(404)
        p=store.root/'images'/name
        if not p.exists():raise HTTPException(404)
        return FileResponse(p)

    @app.get('/api/import-template')
    def template():
        from starlette.responses import Response
        return Response(template_bytes(),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':"attachment; filename*=UTF-8''%E5%95%86%E5%93%81%E5%AF%BC%E5%85%A5%E6%A8%A1%E6%9D%BF.xlsx"})

    @app.post('/api/import/upload')
    async def upload_book(file:UploadFile=File(...)):
        suffix=Path(file.filename or '').suffix.lower()
        if suffix not in ('.xlsx','.xls'):raise ValueError('请选择 .xlsx 或 .xls 文件')
        batch=uuid.uuid4().hex
        p=store.root/'imports'/(batch+suffix)
        try:
            size=0
            with p.open('wb') as output:
                while chunk:=await file.read(1024**2):
                    size+=len(chunk)
                    if size>MAX_IMPORT_BYTES:raise ValueError('Excel 文件超过 500 MB，请拆分后导入')
                    output.write(chunk)
            from starlette.concurrency import run_in_threadpool
            names=await run_in_threadpool(inspect_book,p)
        except ValueError:
            p.unlink(missing_ok=True);raise
        except Exception:
            p.unlink(missing_ok=True);raise ValueError('表格无法读取，请确认未加密并另存为标准 Excel 文件')
        finally:await file.close()
        app.state.previews[batch]={'path':p,'names':names,'time':time.time(),'cache':{}}
        return {'batch':batch,'sheets':names,'filename':file.filename,'fields':FIELDS}

    def get_batch(batch):
        item=app.state.previews.get(batch)
        if not item or time.time()-item['time']>3600:raise ValueError('导入会话已过期，请重新上传')
        return item

    @app.post('/api/import/preview')
    def preview(data:dict):
        b=get_batch(data.get('batch'))
        if data.get('sheet') not in b['names']:raise ValueError('工作表不存在')
        result=preview_import(store,b['path'],data,b['cache'])
        preview_id=uuid.uuid4().hex;b['preview']=result;b['previewId']=preview_id
        return dict(result,previewId=preview_id)

    @app.post('/api/import/commit')
    def commit(data:dict):
        b=get_batch(data.get('batch'))
        if data.get('previewId')!=b.get('previewId'):raise ValueError('预览已变化，请重新确认')
        valid=[r['data'] for r in b['preview']['rows'] if not r['error']]
        if not valid:raise ValueError('没有可以导入的行')
        with store.lock:
            count=store.commit_import(valid)
            app.state.previews.pop(data['batch'],None)
            b['path'].unlink(missing_ok=True)
        return {'count':count}

    @app.put('/api/export-settings')
    def export_settings(data:dict):
        columns=validate_columns(data.get('columns'))
        store.set_value('exportColumns',columns)
        return {'columns':columns}

    @app.post('/api/orders')
    def export(data:dict):
        with store.lock:
            items=store.order_items(data.get('items',[]))
            columns=validate_columns(data.get('columns',store.get_value('exportColumns',list(EXPORT_FIELDS))))
            raw,extension=export_bytes(items,store,data.get('mode','single'),columns)
            store.set_value('exportColumns',columns)
            order_id=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
            name='报货单_'+order_id+extension;p=store.root/'exports'/name
            p.write_bytes(raw);store.save_order(order_id,items,name)
        return {'id':order_id,'filename':name,'url':'/api/exports/'+name}

    @app.get('/api/orders')
    def orders():return store.orders()

    @app.get('/api/exports/{name}')
    def get_export(name:str):
        if Path(name).name!=name or '/' in name or '\\' in name:raise HTTPException(404)
        p=store.root/'exports'/name
        if not p.is_file():raise HTTPException(404,'文件不存在，可能已从备份恢复；请重新开单导出')
        return FileResponse(p,filename=name)

    @app.post('/api/recognize')
    async def ocr(request:Request,file:UploadFile=File(...)):
        if not recognition.available():raise ValueError('离线识别组件未安装；请使用完整软件包或手动录入')
        raw=await upload_bytes(file)
        try:rotation=int(request.query_params.get('rotation',0))
        except ValueError:raise ValueError('旋转角度无效')
        if rotation not in (0,90,180,270):raise ValueError('旋转角度无效')
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(recognition.recognize,raw,rotation,store.products())

    @app.get('/api/backups')
    def backups():return store.backups()

    @app.post('/api/backups')
    def create_backup():return {'name':store.backup()}

    @app.post('/api/backups/restore')
    def restore(data:dict):
        if data.get('confirmation')!='恢复备份':raise ValueError('请输入“恢复备份”确认')
        name=store.restore(data.get('name',''));app.state.previews.clear();return {'safetyBackup':name}

    @app.get('/api/backups/{name}')
    def download_backup(name:str):
        if name not in {b['name'] for b in store.backups()}:raise HTTPException(404)
        return FileResponse(store.root/'backups'/name,filename=name)

    @app.post('/api/shutdown')
    def shutdown():
        if getattr(app.state,'server',None):
            threading.Timer(.7,lambda:setattr(app.state.server,'should_exit',True)).start()
        return {'ok':True}

    return app

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir')
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--updated',action='store_true')
    parser.add_argument('--apply-update',action='store_true')
    parser.add_argument('--update-package-url')
    parser.add_argument('--update-checksum-url')
    parser.add_argument('--update-target-dir')
    parser.add_argument('--update-pid',type=int,default=0)
    args=parser.parse_args()
    if args.apply_update:
        run_update_helper(package_url=args.update_package_url or '',checksum_url=args.update_checksum_url or '',target_dir=args.update_target_dir or '',pid=args.update_pid)
        return
    # Inno Setup uses the same mutex to detect a running installed copy.
    app_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, APP_MUTEX_NAME) if os.name == 'nt' else None
    root=resolve_data_dir(args.data_dir)
    default=default_data_dir().resolve()
    needs_data_location=(
        not args.data_dir
        and root.resolve()==default
        and not (default/'data-location.json').exists()
        and not (root/'counter.sqlite3').exists()
    )
    root.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=root/'app.log',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',encoding='utf8')
    runtime=root/'runtime.json'
    if runtime.exists():
        try:
            import urllib.request
            old=json.loads(runtime.read_text('utf8'))
            if old['url'].startswith('http://127.0.0.1:'):
                with urllib.request.urlopen(old['url']+'/health',timeout=1) as response:
                    health=json.load(response)
                if should_reuse_running_instance(health):
                    if not args.no_browser:webbrowser.open(old['url']+'/?session='+old['token']+('&updated=1' if args.updated else ''))
                    return
        except RuntimeError:
            raise
        except Exception:pass
    app=make_app(root,needs_data_location=needs_data_location)
    app.state.store.daily_backup()
    sock=socket.socket();sock.bind(('127.0.0.1',args.port));sock.listen(128)
    port=sock.getsockname()[1];url=f'http://127.0.0.1:{port}'
    runtime.write_text(json.dumps({'url':url,'token':app.state.token,'pid':os.getpid()}),'utf8')
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_config=None,access_log=False));app.state.server=server
    if not args.no_browser:threading.Timer(1.3,lambda:webbrowser.open(url+'/?session='+app.state.token+('&updated=1' if args.updated else ''))).start()
    if sys.stdout:print('READY '+url,flush=True)
    try:server.run(sockets=[sock])
    finally:
        try:
            if json.loads(runtime.read_text('utf8')).get('pid')==os.getpid():runtime.unlink(missing_ok=True)
        except Exception:pass

if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    try:main()
    except Exception as e:
        logging.exception('Startup failed')
        if getattr(sys,'frozen',False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,'程序启动失败：'+str(e)+'\n请查看数据目录中的 app.log。','档口开单系统',16)
        else:raise
