let mediaDraft={images:[],boxImages:[]},mediaBusy=false,mediaGeneration=0;
const mediaLabels={images:'主图',boxImages:'彩盒'};
function mediaGroup(key){
 const list=mediaDraft[key];
 return '<section class="media-group" data-media-drop="'+key+'"><div class="between"><b>'+mediaLabels[key]+'</b><small>'+list.length+' / 5</small></div><div class="media-tiles">'+list.map((name,i)=>'<div class="media-tile"><img src="/api/images/'+name+'" alt="'+mediaLabels[key]+' '+(i+1)+'"><button type="button" class="image-remove" data-media-remove="'+key+'" data-index="'+i+'" aria-label="删除'+mediaLabels[key]+'第'+(i+1)+'张" '+(mediaBusy?'disabled':'')+'>×</button></div>').join('')+(list.length<5?'<button type="button" class="media-add" data-media-add="'+key+'" aria-label="添加'+mediaLabels[key]+'" '+(mediaBusy?'disabled':'')+'><span>+</span><small>添加图片</small></button>':'')+'</div><input type="file" id="mediaInput-'+key+'" data-media-input="'+key+'" accept="image/jpeg,image/png,image/webp" multiple hidden><small class="media-note">'+(mediaBusy?'正在上传，请稍候…':'可拖入多张图片 · 每张最多 15 MB')+'</small></section>';
}
function renderMedia(){const area=$('#productMedia');if(area)area.innerHTML=Object.keys(mediaLabels).map(mediaGroup).join('')}
async function uploadMedia(key,files){
 if(mediaBusy)return toast('请等待当前图片上传完成');
 const list=Array.from(files||[]);if(!list.length)return;
 if(list.length+mediaDraft[key].length>5)return toast(mediaLabels[key]+'最多上传 5 张，请减少选择的图片');
 if(list.some(f=>!['image/jpeg','image/png','image/webp'].includes(f.type)||f.size>15*1024*1024))return toast('请上传 JPG、PNG、WEBP，每张不超过 15 MB');
 const generation=mediaGeneration,target=mediaDraft[key];mediaBusy=true;renderMedia();
 const save=$('[form="productForm"]');if(save)save.disabled=true;
 try{for(const file of list){const fd=new FormData();fd.append('file',file);const r=await api('/api/images',{method:'POST',body:fd});if(generation!==mediaGeneration)return;target.push(r.image)}}
 catch(e){toast(e.message)}finally{mediaBusy=false;if(generation===mediaGeneration){renderMedia();if(save)save.disabled=false}}
}
function newForm(id){
 if(mediaBusy)return toast('图片正在上传，请稍候');
 const p=products.find(p=>p.id===id)||{cat:'日用百货',volume:0};mediaGeneration++;
 mediaDraft={images:[...(p.images||(p.image?[p.image]:[]))],boxImages:[...(p.boxImages||[])]};
 const fields=[['code','销售编码',true],['factoryCode','厂家编码',true],['name','商品名称',true],['factory','厂家名称',false],['pack','装箱数（个 / 件）',false],['price','出厂价（元 / 个）',false],['size','尺寸',false],['battery','电池容量',false],['charger','充电头 / 接口',false],['volume','单件体积（m³）',false],['cat','商品分类',false]];
 openDialog(id?'编辑商品资料':'新增商品','保存后写入本机数据库。','<form id="productForm" data-id="'+(id||'')+'"><div id="productMedia" class="product-media">'+Object.keys(mediaLabels).map(mediaGroup).join('')+'</div><div class="form-grid">'+fields.map(([k,l,required])=>'<label><span class="form-label">'+l+(required?' <em class="required-mark">*</em>':'')+'</span><input name="'+k+'" value="'+esc(p[k]??'')+'" '+(k==='pack'?'type="number" min="1" max="1000000" step="1"':k==='price'?'type="number" min="0" max="100000000" step="0.01"':k==='volume'?'type="number" min="0" max="100000000" step="0.000001"':'maxlength="300"')+(required?' required':'')+'></label>').join('')+'<label style="grid-column:1/-1"><span class="form-label">备注</span><textarea name="notes" maxlength="300">'+esc(p.notes||'')+'</textarea></label></div></form>','<small>销售编码唯一；厂家编码在同一厂家内唯一。</small><button class="primary" type="submit" form="productForm">保存商品</button>');
}
async function saveProduct(form){
 if(mediaBusy)return toast('请等待图片上传完成');if(!form.reportValidity())return;
 const button=$('[form="productForm"]');button.disabled=true;
 try{const data=Object.fromEntries(new FormData(form)),id=Number(form.dataset.id);data.images=[...mediaDraft.images];data.boxImages=[...mediaDraft.boxImages];for(const key of ['pack','price','volume'])data[key]=Number(data[key]||0);await api(id?'/api/products/'+id:'/api/products',{method:id?'PUT':'POST',body:data});closeDialog();await refreshProducts();toast('商品资料已保存到本机')}
 catch(e){toast(e.message)}finally{button.disabled=false}
}
function detail(id){
 const p=products.find(x=>x.id===id);if(!p)return;
 const galleries=Object.entries(mediaLabels).map(([key,label])=>{const list=p[key]||(key==='images'&&p.image?[p.image]:[]);return '<section class="detail-gallery"><b>'+label+'</b><div class="detail-images">'+(list.length?list.map((name,i)=>'<a href="/api/images/'+name+'" target="_blank" rel="noreferrer"><img src="/api/images/'+name+'" alt="'+label+' '+(i+1)+'"></a>').join(''):'<div class="media-empty">暂无'+label+'</div>')+'</div></section>'}).join('');
 openDialog('商品资料','编码、规格与厂家信息','<div class="between"><div><span class="tag">'+esc(p.cat)+'</span><h2>'+esc(p.name)+'</h2></div><div><small>出厂价 / 个</small><div style="font-size:27px">'+money(p.price)+'</div></div></div><div class="product-media detail-media">'+galleries+'</div><div class="mapping"><div><small>销售编码</small><div class="mono code">'+esc(p.code)+'</div></div>'+icon('arrow')+'<div><small>厂家编码</small><div class="mono">'+esc(p.factoryCode)+'</div></div></div><div class="section-label">商品规格与包装</div><div class="fields">'+[['厂家名称',p.factory],['装箱数',p.pack+' 个 / 件'],['产品尺寸',p.size],['电池容量',p.battery],['充电头 / 接口',p.charger],['单件体积',p.volume+' m³'],['备注',p.notes]].map(([label,value])=>'<div class="field"><small>'+label+'</small><b>'+esc(value||'—')+'</b></div>').join('')+'</div>','<button data-action="edit" data-id="'+id+'">修改资料</button><button class="primary" data-action="detailPick" data-id="'+id+'">'+(selected.has(id)?'从待开单移除':'加入待开单')+'</button>');
}
document.addEventListener('click',e=>{const add=e.target.closest('[data-media-add]'),remove=e.target.closest('[data-media-remove]');if(add&&!add.disabled)$('#mediaInput-'+add.dataset.mediaAdd)?.click();if(remove&&!mediaBusy){mediaDraft[remove.dataset.mediaRemove].splice(Number(remove.dataset.index),1);renderMedia()}});
document.addEventListener('change',e=>{if(e.target.dataset.mediaInput)uploadMedia(e.target.dataset.mediaInput,e.target.files)});
document.addEventListener('dragover',e=>{const zone=e.target.closest('[data-media-drop]');if(zone){e.preventDefault();zone.classList.add('dragging')}});
document.addEventListener('dragleave',e=>{const zone=e.target.closest('[data-media-drop]');if(zone&&!zone.contains(e.relatedTarget))zone.classList.remove('dragging')});
document.addEventListener('drop',e=>{const zone=e.target.closest('[data-media-drop]');if(zone){e.preventDefault();zone.classList.remove('dragging');uploadMedia(zone.dataset.mediaDrop,e.dataTransfer.files)}});

let exportOrderKeys=[],exportChecked=new Set(),exportDragKey='';
function selectedExportColumns(){return exportOrderKeys.filter(k=>exportChecked.has(k))}
function drawExportFields(){
 const area=$('#exportFields');if(!area)return;
 area.innerHTML=exportOrderKeys.map((key,i)=>'<div class="export-field" draggable="true" data-export-key="'+key+'"><span class="export-grip" aria-hidden="true">⠿</span><label><input type="checkbox" data-export-check="'+key+'" '+(exportChecked.has(key)?'checked':'')+'>'+esc(appState.exportFields[key])+'</label><button type="button" data-export-move="'+key+'" data-step="-1" aria-label="上移'+esc(appState.exportFields[key])+'" '+(i===0?'disabled':'')+'>↑</button><button type="button" data-export-move="'+key+'" data-step="1" aria-label="下移'+esc(appState.exportFields[key])+'" '+(i===exportOrderKeys.length-1?'disabled':'')+'>↓</button></div>').join('');
 $('#exportFieldCount').textContent='已选 '+exportChecked.size+' 项';
}
const baseOrder=order;
order=function(){
 if(!selected.size)return baseOrder();baseOrder();
 const all=Object.keys(appState.exportFields),saved=(appState.exportColumns||all).filter(k=>all.includes(k));
 exportOrderKeys=[...saved,...all.filter(k=>!saved.includes(k))];exportChecked=new Set(saved);
 $('#orderTotals').insertAdjacentHTML('afterend','<details class="export-config"><summary>导出字段与顺序 <small id="exportFieldCount"></small></summary><p>勾选需要的字段，拖动或点击箭头调整顺序。</p><div id="exportFields"></div><button type="button" data-action="saveExportFields">保存字段配置</button></details>');drawExportFields();
};
document.addEventListener('change',e=>{const key=e.target.dataset.exportCheck;if(!key)return;e.target.checked?exportChecked.add(key):exportChecked.delete(key);$('#exportFieldCount').textContent='已选 '+exportChecked.size+' 项'});
document.addEventListener('click',async e=>{const b=e.target.closest('[data-export-move]');if(b&&!b.disabled){const i=exportOrderKeys.indexOf(b.dataset.exportMove),j=i+Number(b.dataset.step);[exportOrderKeys[i],exportOrderKeys[j]]=[exportOrderKeys[j],exportOrderKeys[i]];drawExportFields()}const save=e.target.closest('[data-action="saveExportFields"]');if(save){save.disabled=true;try{const r=await api('/api/export-settings',{method:'PUT',body:{columns:selectedExportColumns()}});appState.exportColumns=r.columns;toast('导出字段与顺序已保存')}catch(err){toast(err.message)}finally{save.disabled=false}}});
document.addEventListener('dragstart',e=>{const row=e.target.closest('[data-export-key]');if(row){exportDragKey=row.dataset.exportKey;e.dataTransfer.setData('text/plain',exportDragKey);e.dataTransfer.effectAllowed='move'}});
document.addEventListener('dragover',e=>{if(exportDragKey&&e.target.closest('[data-export-key]')){e.preventDefault();e.dataTransfer.dropEffect='move'}});
document.addEventListener('drop',e=>{const row=e.target.closest('[data-export-key]');if(!row||!exportDragKey)return;e.preventDefault();const from=exportOrderKeys.indexOf(exportDragKey),to=exportOrderKeys.indexOf(row.dataset.exportKey);if(from>=0&&to>=0){exportOrderKeys.splice(to,0,exportOrderKeys.splice(from,1)[0]);drawExportFields()}exportDragKey=''});
document.addEventListener('dragend',()=>{exportDragKey=''});

// Remove the prototype-only helper copy and batch-query prompt from the
// production page. The base template still contains the legacy markup because
// it is also used by the design prototype.
const productionRender=render;
render=function(){productionRender();document.querySelector('.batch-example')?.remove();document.querySelector('.library-helper')?.remove()};

// Keep the empty supplier state concise: the page title is enough when no
// supplier has been maintained yet.
suppliers=function(){const supplierNames=[...new Set(products.map(p=>p.factory).filter(Boolean))];if(!supplierNames.length){openDialog('合作厂家','','<div class="empty"><h3>暂无厂家</h3></div>');return}openDialog('合作厂家','选择厂家后查看对应商品','<div class="stack">'+supplierNames.map(f=>{let ps=products.filter(p=>p.factory===f);return '<div class="panel" style="padding:18px"><div class="between"><div><h3>'+esc(f)+'</h3><small>'+ps.length+' 款商品</small></div><button data-action="filterFactory" data-factory="'+esc(f)+'">查看商品</button></div></div>'}).join('')+'</div>')};
