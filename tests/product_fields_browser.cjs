const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');

(async()=>{
 const folder=path.resolve(process.argv[2]||'test-review-product-fields');
 const runtime=JSON.parse(fs.readFileSync(path.join(folder,'runtime.json'),'utf8'));
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1366,height:900}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(runtime.url+'/?session='+runtime.token);
  await page.locator('.library-title').waitFor();
  assert.equal(await page.locator('[data-select]').count(),1);
  await page.locator('[data-action="edit"][data-id]').first().click();
  assert.equal(await page.locator('[name="color"]').inputValue(),'红色');
  assert.equal(await page.locator('[name="cartonSize"]').inputValue(),'40×30×20 cm');
  assert.equal(await page.locator('[name="cartonWeight"]').inputValue(),'12.345');
  assert.equal(await page.locator('[name="material"]').inputValue(),'不锈钢');
  await page.locator('[name="parameters"]').fill('容量 500ml\n耐温 100℃');
  await page.locator('[form="productForm"]').click();
  await page.locator('[data-action="detail"][data-id]').first().click();
  for(const value of ['红色','40×30×20 cm','12.345 kg','不锈钢','容量 500ml'])
   assert((await page.locator('#dialog').innerText()).includes(value),value);
  await page.locator('[data-action="productDelete"]').last().click();
  assert.equal(await page.locator('#deleteProductCode').count(),0);
  assert((await page.locator('#dialog').innerText()).includes('确定删除'));
  await page.locator('[data-action="productDeleteConfirm"]').click();
  await page.waitForFunction(()=>document.querySelectorAll('[data-select]').length===0);
  for(const [code,name] of [['BULK-01','批量测试一'],['BULK-02','批量测试二']]){
   const response=await page.request.post(runtime.url+'/api/products',{headers:{'X-Counter-Request':'1'},data:{code,factoryCode:code,name,factory:'测试厂',pack:12,price:3}});
   assert.equal(response.status(),200,await response.text());
  }
  await page.reload();
  await page.locator('[data-select]').first().waitFor();
  await page.locator('[data-select]').first().check();
  await page.locator('[data-select]').last().check();
  const bulk=page.locator('.selectedbar [data-action="productsBulkDelete"]');
  assert(await bulk.isEnabled());
  assert.equal(await page.locator('.selectedbar [data-action="order"]').count(),1);
  await bulk.click();
  assert((await page.locator('#dialog').innerText()).includes('将删除 2 款商品'));
  await page.locator('[data-action="productsBulkDeleteConfirm"]').click();
  await page.waitForFunction(()=>document.querySelectorAll('[data-select]').length===0);
  assert(await bulk.isDisabled());
  assert.deepEqual(errors,[]);
  console.log('PASS: product edit, new fields, detail, single and bulk delete confirmation');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
