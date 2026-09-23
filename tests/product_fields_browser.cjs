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
  await page.locator('#deleteProductCode').fill('DEMO-01');
  await page.locator('[data-action="productDeleteConfirm"]').click();
  await page.waitForFunction(()=>document.querySelectorAll('[data-select]').length===0);
  assert.deepEqual(errors,[]);
  console.log('PASS: product edit, new fields, detail, delete confirmation');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
