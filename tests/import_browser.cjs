const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert');
(async()=>{
 const dir=path.resolve('test-packaged'),runtime=JSON.parse(fs.readFileSync(path.join(dir,'runtime.json'),'utf8'));
 const browser=await chromium.launch({channel:'chrome',headless:true});const page=await browser.newPage({acceptDownloads:true});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
 await page.goto(runtime.url+'/?session='+runtime.token);await page.locator('.library-title').waitFor();
 await page.locator('[data-action="import"]').click();await page.locator('#bookInput').setInputFiles(path.join(dir,'import-fixture.xlsx'));
 await page.locator('#importFactory').waitFor();await page.locator('#importFactory').fill('第二厂家');await page.locator('#importPrefix').fill('B');
 await page.locator('[data-action="importValidate"]').click();await page.getByText('共 2 行 · 可导入 1 行 · 问题行 1 行',{exact:true}).waitFor();
 await page.locator('[data-action="importCommit"]').click();await page.getByText('B-01',{exact:true}).waitFor();
 await page.locator('#search').fill('A-13 B-01');await page.locator('[data-action="search"]').click();assert.equal(await page.locator('[data-select]').count(),2);
 await page.locator('#selectAll').check();await page.locator('[data-action="order"]').click();
 await page.locator('[name="exportMode"][value="multiple"]').check();
 const download=page.waitForEvent('download');await page.locator('[data-action="export"]').click();await(await download).saveAs(path.join(dir,'two-factory.zip'));
 await page.locator('[data-action="close"]').first().click();
 await page.locator('[data-action="shutdown"]').click();await page.locator('[data-action="shutdownConfirm"]').click();await page.getByText('系统已退出',{exact:true}).waitFor();
 assert.deepEqual(errors,[]);console.log('PASS: packaged Excel upload/mapping/validation/commit/batch search/multi-factory ZIP/save-and-exit');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
