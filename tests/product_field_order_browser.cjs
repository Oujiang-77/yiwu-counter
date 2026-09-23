const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');

(async()=>{
 const folder=path.resolve(process.argv[2]||'test-review-product-fields');
 const runtime=JSON.parse(fs.readFileSync(path.join(folder,'runtime.json'),'utf8'));
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:900}});
 const defaults=['code','factoryCode','name','factory','color','size','cartonSize','cartonWeight','material','pack','price','battery','charger','volume','cat','parameters','notes'];
 try{
  await page.goto(runtime.url+'/?session='+runtime.token);
  await page.locator('[data-action="edit"][data-id]').first().click();
  assert.equal(await page.locator('#productFieldGrid').evaluate(el=>getComputedStyle(el).gridTemplateColumns.split(' ').length),3);
  await page.locator('[name="color"]').fill('未保存的颜色');
  await page.locator('[data-product-field-grip="material"]').dragTo(page.locator('[data-product-field="code"]'));
  await page.waitForFunction(()=>document.querySelector('#productFieldGrid')?.firstElementChild?.dataset.productField==='material');
  assert.equal(await page.locator('[name="color"]').inputValue(),'未保存的颜色');
  await page.locator('[data-action="close"]').last().click();
  await page.reload();
  await page.locator('[data-action="edit"][data-id]').first().click();
  assert.equal(await page.locator('#productFieldGrid').evaluate(el=>el.firstElementChild.dataset.productField),'material');
  await page.locator('[data-action="close"]').last().click();
  await page.locator('[data-action="detail"][data-id]').first().click();
  assert.equal(await page.locator('.product-detail-fields').evaluate(el=>el.firstElementChild.dataset.detailField),'material');
  assert.equal(await page.locator('[data-detail-field="color"] b').innerText(),'红色');
  console.log('PASS: three-column editor, drag order persisted, detail follows order, input preserved');
 }finally{
  await page.request.put(runtime.url+'/api/product-field-order',{headers:{'X-Counter-Request':'1'},data:{order:defaults}}).catch(()=>{});
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exit(1)});
