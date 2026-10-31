const fs=require('fs');const{chromium}=require('playwright');
(async()=>{const browser=await chromium.launch({headless:true,args:['--no-sandbox']});try{
 const source=fs.readFileSync('apps/android/app/src/main/assets/fox-browser.js','utf8');
 if(source!==fs.readFileSync('apps/desktop/ServiceLib/Resources/fox-browser.js','utf8'))throw Error('Browser bridge copies differ');
 const context=await browser.newContext();let messages=[];const page=await context.newPage();
 await page.exposeFunction('capture',value=>messages.push(JSON.parse(value)));
 await page.addInitScript({content:"window.dicodeFox={postMessage:value=>window.capture(value)};\n"+source.replace('__DICODE_NONCE__',JSON.stringify('fixture-nonce'))});
 await page.route('https://accounts.firefox.com/**',route=>route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><html><body>Owned WebChannel test fixture</body></html>'}));
 await page.goto('https://accounts.firefox.com/');
 const responses=await page.evaluate(()=>{
  let result=[];window.addEventListener('WebChannelMessageToContent',e=>result.push(typeof e.detail==='string'?JSON.parse(e.detail):e.detail));
  function send(command,data,id){document.dispatchEvent(new CustomEvent('WebChannelMessageToChrome',{bubbles:true,detail:JSON.stringify({id:'account_updates',message:{command,data,messageId:id}})}));}
  send('fxaccounts:fxa_status',{},'status');send('fxaccounts:can_link_account',{},'link');
  send('fxaccounts:login',{email:'fixture@example.test',sessionToken:'12'.repeat(32),verified:false},'login');
  return result;
 });
 if(!responses.some(r=>r.message.command==='fxaccounts:fxa_status')||!responses.some(r=>r.message.command==='fxaccounts:can_link_account'))throw Error('WebChannel reply missing');
 if(messages.length)throw Error('Unconfirmed session delivered too early');
 await page.evaluate(()=>history.pushState({},'', '/signin/confirmed'));
 await page.waitForFunction(()=>window.__dicodeFoxHooked);
 await new Promise(r=>setTimeout(r,100));
 if(messages.length!==1||messages[0].nonce!=='fixture-nonce'||messages[0].session_token!=='12'.repeat(32))throw Error('Verified handoff missing/duplicated');
 await page.evaluate(()=>window.__dicodeFoxRetry());await new Promise(r=>setTimeout(r,100));
 if(messages.length!==2)throw Error('Interactive retry is broken');
 const foreign=await context.newPage();let leaks=[];await foreign.exposeFunction('capture',v=>leaks.push(v));
 await foreign.addInitScript({content:"window.dicodeFox={postMessage:value=>window.capture(value)};\n"+source.replace('__DICODE_NONCE__',JSON.stringify('fixture-nonce'))});
 await foreign.route('https://foreign.invalid/**',r=>r.fulfill({status:200,contentType:'text/html',body:'<html><body>Foreign fixture</body></html>'}));await foreign.goto('https://foreign.invalid/');
 if(await foreign.evaluate(()=>!!window.__dicodeFoxHooked))throw Error('Bridge installed on foreign origin');
 if(leaks.length)throw Error('Foreign session leaked');
 console.log('PASS actual Chromium WebChannel: status/link replies, OTP handoff, deduplication, retry, origin isolation');
 }finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
