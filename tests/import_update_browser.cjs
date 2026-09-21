const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{
 const folder=path.resolve('test-import-update'),runtime=JSON.parse(fs.readFileSync(path.join(folder,'runtime.json'),'utf8'));
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1080}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(runtime.url+'/?session='+runtime.token);await page.locator('.library-title').waitFor();
  await page.locator('[data-action="import"]').click();
  await page.locator('[data-import-dropzone]').waitFor();
  const b64=fs.readFileSync(path.join(folder,'fixture.xlsx')).toString('base64');
  await page.locator('[data-import-dropzone]').evaluate((zone,base64)=>{
   const data=new DataTransfer();data.items.add(new File([Uint8Array.from(atob(base64),c=>c.charCodeAt(0))],'fixture.xlsx',{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}));
   zone.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:data}));
  },b64);
  await page.locator('#importFactory').waitFor();
  assert.equal(await page.locator('.import-section').count(),3);
  assert.equal(await page.locator('.import-mappings .required-mark').count(),3);
  assert.equal(await page.locator('[data-import-field="code"] option:checked').textContent(),'');
  const rects=await page.locator('#importSheet,#importHeader,[data-action="importReloadHeaders"]').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().bottom));
  assert.ok(Math.max(...rects)-Math.min(...rects)<3,rects);
  await page.screenshot({path:path.join(folder,'mapping-desktop.png'),fullPage:true});
  await page.locator('#importFactory').fill('浏览器测试厂');await page.locator('#importPrefix').fill('UI');
  await page.locator('[data-action="importValidate"]').click();
  await page.getByText('共 1 行 · 可导入 1 行 · 问题行 0 行',{exact:true}).waitFor();
  await page.locator('[data-action="importNext"]').click();
  await page.locator('[data-import-field="name"]').selectOption('');
  await page.locator('[data-action="importValidate"]').click();
  await page.getByText('共 1 行 · 可导入 0 行 · 问题行 1 行',{exact:true}).waitFor();
  await page.locator('[data-action="importNext"]').click();
  await page.locator('[data-import-field="name"]').selectOption('1');
  await page.locator('[data-action="importValidate"]').click();
  await page.locator('[data-action="importCommit"]').click();
  await page.getByText('UI-01',{exact:true}).waitFor();
  assert.deepEqual(errors,[]);console.log('PASS: drag drop, 3 sections, inline reader, blank mapping, required marks, validation and commit');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
