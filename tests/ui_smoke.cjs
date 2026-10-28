// Run only against a disposable test instance with an admin session supplied
// through INVENTORY_SMOKE_SESSION_FILE. The scenario activates the new mode.
const { chromium } = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');

(async () => {
  const url = process.env.INVENTORY_SMOKE_URL || 'http://127.0.0.1:8765';
  const session = JSON.parse(fs.readFileSync(process.env.INVENTORY_SMOKE_SESSION_FILE, 'utf8'));
  const browser = await chromium.launch({headless:true,
    ...(process.env.INVENTORY_SMOKE_CHROMIUM ? {executablePath:process.env.INVENTORY_SMOKE_CHROMIUM,
      args:['--no-sandbox','--no-zygote','--disable-dev-shm-usage','--single-process']} : {})});
  const context = await browser.newContext({viewport:{width:1440,height:1080}});
  await context.addCookies([{name:'inv_session',value:session.token,url}]);
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const clickTab = async name => page.getByRole('button',{name,exact:true}).click();
  const saved = async () => {
    await page.waitForFunction(()=>document.querySelector('#message').textContent==='Tersimpan di server.');
    await page.locator('#message').evaluate(el=>el.textContent='');
  };
  const saveProduct = async (code, name, kind, unit, shelf, kitchen) => {
    const form=page.locator('[data-form="product"]');
    await form.locator('[name=code]').fill(code);
    await form.locator('[name=name]').fill(name);
    await form.locator('[name=kind]').selectOption(kind);
    await form.locator('[name=base_uom]').fill(unit);
    if(shelf!==null)await form.locator('[name=shelf_life_days]').fill(String(shelf));
    if(kitchen)await form.locator('[name=kitchen_id]').selectOption({label:kitchen});
    if(unit==='pcs')await form.locator('[name=discrete]').check();
    await form.getByRole('button',{name:'Simpan produk'}).click();
    await saved();
  };
  try {
    await page.goto(url+'/manufacturing');
    await page.getByRole('heading',{name:'Persiapan manufaktur'}).waitFor();
    await page.locator('[name=ack]').check();
    await page.getByRole('button',{name:'Aktifkan fondasi server'}).click();
    await saved();
    await clickTab('Dapur');
    assert.equal(await page.locator('.kitchen').count(),11);
    await clickTab('Produk');
    await saveProduct('SMOKE-FLOUR','Tepung uji','raw','kg',null,null);
    await saveProduct('SMOKE-BREAD','Roti uji','finished','pcs',3,'D01 · Dapur 1');
    await saveProduct('SMOKE-WHITE','Putih telur uji','byproduct','kg',2,null);
    await clickTab('BOM');
    await page.locator('[name=product_id]').selectOption({label:'SMOKE-BREAD · Roti uji'});
    await page.locator('[name=output_qty]').fill('40');
    await page.getByRole('button',{name:'Tambah bahan',exact:true}).click();
    await page.locator('[name=material-product-0]').selectOption({label:'SMOKE-FLOUR · Tepung uji'});
    await page.locator('[name=material-qty-0]').fill('1');
    await page.locator('[name=material-uom-0]').fill('kg');
    await page.getByRole('button',{name:'Tambah overhead',exact:true}).click();
    await page.locator('[name=overhead-name-0]').fill('Gas');
    await page.getByRole('button',{name:'Tambah turunan',exact:true}).click();
    await page.locator('[name=byproduct-product-0]').selectOption({label:'SMOKE-WHITE · Putih telur uji'});
    await page.locator('[name=byproduct-qty-0]').fill('0.5');
    await page.getByRole('button',{name:'Simpan draft BOM'}).click();
    await saved();
    await page.getByRole('button',{name:'Aktifkan',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('BOM aktif.'));
    page.once('dialog',dialog=>dialog.accept('80'));
    await page.getByRole('button',{name:'Hitung kebutuhan'}).click();
    await page.locator('#simulation').getByRole('heading',{name:'Kebutuhan untuk 80'}).waitFor();
    assert.match(await page.locator('#simulation').innerText(),/Tepung uji/);
    await page.screenshot({path:'/tmp/inventory-bom-desktop.png',fullPage:true});

    await clickTab('Stok & pemakaian');
    const receipt=page.locator('[data-form=receipt]');
    await receipt.locator('[name=warehouse_id]').selectOption({label:'GDC · Gudang Central'});
    await receipt.locator('[name=product_id]').selectOption({label:'SMOKE-FLOUR · Tepung uji'});
    await receipt.locator('[name=qty]').fill('10');
    await receipt.locator('[name=batch_number]').fill('SMOKE-LOT');
    await receipt.locator('[name=expiry_date]').fill('2099-12-31');
    await receipt.locator('[name=unit_cost]').fill('20000');
    await receipt.locator('[name=reference]').fill('SMOKE-IN');
    await receipt.getByRole('button',{name:'Catat penerimaan'}).click();
    await saved();
    await clickTab('Transfer');
    const ship=page.locator('[data-form=ship]');
    await ship.locator('[name=source_id]').selectOption({label:'GDC · Gudang Central'});
    await ship.locator('[name=destination_id]').selectOption({label:'G-D01 · Gudang Dapur 1'});
    await ship.locator('[name=product_id]').selectOption({label:'SMOKE-FLOUR · Tepung uji'});
    await ship.locator('[name=qty]').fill('3');
    await ship.locator('[name=reference]').fill('SMOKE-TRF');
    await ship.getByRole('button',{name:'Kirim dengan FEFO'}).click();
    await saved();
    const receive=page.locator('[data-form=receive-transfer]');
    await receive.locator('input[type=number]').fill('2');
    await receive.getByRole('button',{name:'Konfirmasi penerimaan'}).click();
    await saved();
    assert.match(await page.locator('#content').innerText(),/partial/);
    await page.locator('[data-form=receive-transfer] input[type=number]').fill('1');
    await page.getByRole('button',{name:'Konfirmasi penerimaan'}).click();
    await saved();
    assert.match(await page.locator('#content').innerText(),/received/);
    await clickTab('Stok & pemakaian');
    assert.match(await page.locator('#content').innerText(),/SMOKE-LOT/);
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'/tmp/inventory-stock-mobile.png',fullPage:true});
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);
    assert.equal(overflow,false,'Page should not overflow on mobile');
    assert.deepEqual(errors,[]);
    console.log('Browser smoke passed: activate, 11 kitchens, product/BOM, simulation, receipt, partial/full transfer, mobile layout.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});

