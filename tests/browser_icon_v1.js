// Icono real bajo proxy Ingress + banner simulado. No sustituye la API.
const {launchBrowser} = require('./browser_support');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const [origin,out] = process.argv.slice(2);
const prefix = '/api/hassio_ingress/icon-test/';
const result = {realBackend:true,realHomeAssistant:false,cases:[],errors:[]};
const check = (condition,name) => {assert.ok(condition,name);result.cases.push(name);};
(async()=>{
 let browser;
 const proxy=http.createServer(async(req,res)=>{
  try {
   if(req.url==='/panel') {
    res.writeHead(200,{'Content-Type':'text/html; charset=utf-8'});
    res.end(`<html><meta name="viewport" content="width=device-width, initial-scale=1"><style>html,body{margin:0;height:100%;overflow:hidden}header{height:56px;background:#03a9f4;color:white;display:flex;align-items:center;padding:0 16px;box-sizing:border-box;font:16px system-ui}main{height:calc(100vh - 56px);overflow:hidden}iframe{display:block;width:100%;height:100vh;border:0}</style><header>Home Assistant · simulación local</header><main><iframe src="${prefix}"></iframe></main></html>`);
    return;
   }
   if(!req.url.startsWith(prefix)){res.writeHead(404);res.end();return;}
   const chunks=[];for await(const c of req)chunks.push(c);
   const headers={...req.headers,'x-ingress-path':prefix.slice(0,-1)};
   delete headers.host;delete headers.connection;delete headers['content-length'];
   const options={method:req.method,headers};
   if(chunks.length)options.body=Buffer.concat(chunks);
   const upstream=await fetch(origin+'/'+req.url.slice(prefix.length),options);
   const forwarded={};for(const [k,v] of upstream.headers)if(!['connection','transfer-encoding','content-length','content-encoding'].includes(k))forwarded[k]=v;
   const body=Buffer.from(await upstream.arrayBuffer());
   res.writeHead(upstream.status,forwarded);res.end(body);
  }catch(error){res.writeHead(502);res.end('Proxy de prueba no disponible');}
 });
 await new Promise(resolve=>proxy.listen(0,'127.0.0.1',resolve));
 try {
  fs.mkdirSync(out,{recursive:true});
  browser=await launchBrowser();
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  page.on('pageerror',error=>result.errors.push(error.message));
  const proxyOrigin=`http://127.0.0.1:${proxy.address().port}`;
  await page.goto(proxyOrigin+'/panel');
  const app=page.frameLocator('iframe');
  await app.locator('.day-card').first().waitFor();
  await app.locator('.brand-mark img').waitFor();
  check(await app.locator('.brand-mark img').evaluate(img=>img.complete&&img.naturalWidth===192),'approved-icon-loaded-in-app');
  const links=await app.locator('link[rel="icon"],link[rel="apple-touch-icon"]').evaluateAll(nodes=>nodes.map(node=>node.href));
  check(links.length===5&&links.every(url=>url.includes(prefix+'static/')),'all-favicons-preserve-ingress-prefix');
  for(const url of links){const response=await page.request.get(url);check(response.ok(),'favicon-http-'+new URL(url).pathname.split('/').at(-1));}
  check((await app.locator('#app-version').textContent())==='v1.1.0','stable-version-visible');
  for(const width of [320,390,850,851,1280]) {
   await page.setViewportSize({width,height:900});
   check(await app.locator('html').evaluate(el=>el.scrollWidth<=innerWidth),`no-overflow-${width}`);
   check(await app.locator('.brand-mark img').isVisible(),`brand-visible-${width}`);
   check(await app.locator('.brand-mark img').evaluate(img=>{const r=img.getBoundingClientRect();return r.width>0&&r.width<=48&&r.height<=48&&getComputedStyle(img).objectFit==='contain';}),`image-contained-${width}`);
   if(width===390){
    await app.locator('.main-nav').evaluate(async nav=>{for(let n=0;n<30&&nav.getBoundingClientRect().bottom>innerHeight-55;n++)await new Promise(resolve=>setTimeout(resolve,20));});
    check(await app.locator('.main-nav').evaluate(nav=>nav.getBoundingClientRect().bottom<=innerHeight-55),'mobile-nav-clear-of-banner');
    await page.screenshot({path:path.join(out,'icono-app-movil.png')});
   }
  }
  await page.screenshot({path:path.join(out,'icono-app-escritorio.png')});
  check(result.errors.length===0,'no-js-errors');
  result.success=true;
 }finally{
  if(browser)await browser.close();
  proxy.closeAllConnections();await new Promise(resolve=>proxy.close(resolve));
  fs.writeFileSync(path.join(out,'branding.json'),JSON.stringify(result,null,2));
 }
 console.log(JSON.stringify(result,null,2));
})().catch(error=>{console.error(error);process.exitCode=1;});
