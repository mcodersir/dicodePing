const fs=require('fs');const crypto=require('crypto');const{chromium}=require('playwright');
(async()=>{const browser=await chromium.launch({headless:true,args:['--no-sandbox']});try{
 const source=fs.readFileSync(process.env.FOX_BROWSER_SOURCE||'apps/android/app/src/main/assets/fox-browser.js','utf8');
 if(!process.env.FOX_BROWSER_SOURCE && source!==fs.readFileSync('apps/desktop/ServiceLib/Resources/fox-browser.js','utf8'))throw Error('Browser bridge copies differ');
 const context=await browser.newContext();let authErrors=[],messages=[];const page=await context.newPage();
 let pendingSession=null;
 await page.exposeFunction('capture',async value=>{
  const data=JSON.parse(value);
  if(data.kind==='auth_progress')return;
  if(data.kind==='auth_error'){authErrors.push(data);return;}
  if(data.kind==='pending_session'){pendingSession=data;return;}
  if(data.kind==='bridge_ready'){
   if(pendingSession)await page.evaluate(([token,email])=>window.__dicodeFoxRestore(token,email),[pendingSession.session_token,pendingSession.email]);
   return;
  }
  messages.push(data);
 });
 await page.addInitScript({content:"window.dicodeFox={postMessage:value=>window.capture(value)};\n"+source.replace('__DICODE_NONCE__',JSON.stringify('fixture-nonce'))});
 await page.route('https://accounts.firefox.com/**',route=>route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><html><body>Owned WebChannel test fixture</body></html>'}));
 let exchangeCount=0,exchangeError=null,reject=false,blocked=false,mismatch=false,codeChallenge="",codeState="",codeCalls=0;
 await context.addCookies([{name:'signin-fixture',value:'earned',domain:'api.accounts.firefox.com',path:'/',secure:true,sameSite:'None'}]);
 await page.route('https://api.accounts.firefox.com/v1/oauth/token',async route=>{
  const request=route.request(),headers={'Access-Control-Allow-Origin':'https://accounts.firefox.com','Access-Control-Allow-Headers':'authorization,content-type','Access-Control-Allow-Methods':'POST','Access-Control-Allow-Credentials':'true'};
  if(request.method()==='OPTIONS'){await route.fulfill({status:204,headers});return;}
  try {
   exchangeCount++;
   if(request.method()!=='POST')throw Error('OAuth method');
   if(!(await request.allHeaders()).cookie?.includes('signin-fixture=earned'))throw Error('Browser OAuth dropped the sign-in cookie');
   const h=Object.fromEntries([...request.headers().authorization.matchAll(/(id|ts|nonce|mac|hash)="([^"]+)"/g)].map(m=>[m[1],m[2]]));
   const key=[Buffer.from('12'.repeat(32),'hex'),Buffer.from('34'.repeat(32),'hex')].map(session=>Buffer.from(crypto.hkdfSync('sha256',session,Buffer.alloc(32),'identity.mozilla.com/picl/v1/sessionToken',64))).find(k=>k.subarray(0,32).toString('hex')===h.id);
   if(!key)throw Error('Invalid OAuth Hawk key derivation');
   const hash=crypto.createHash('sha256').update('hawk.1.payload\napplication/json\n'+request.postData()+'\n').digest('base64');
   const normalized=`hawk.1.header\n${h.ts}\n${h.nonce}\nPOST\n/v1/oauth/token\napi.accounts.firefox.com\n443\n${hash}\n\n`;
   const mac=crypto.createHmac('sha256',key.subarray(32)).update(normalized).digest('base64');
   if(h.hash!==hash || h.mac!==mac || Math.abs(Date.now()/1000-Number(h.ts))>10)throw Error('Invalid signed browser OAuth request');
   const body=JSON.parse(request.postData());if(body.client_id!=='5882386c6d801776'||body.grant_type!=='fxa-credentials'||body.access_type!=='offline')throw Error('OAuth scope/body changed');
  }catch(error){exchangeError=error;}
  await route.fulfill({status:blocked?406:reject?400:200,headers,contentType:'application/json',body:JSON.stringify(blocked?{}:reject?{errno:104}:{access_token:'a1'.repeat(32),refresh_token:'b2'.repeat(32),expires_in:3600})});
 });
 const cors={'Access-Control-Allow-Origin':'https://accounts.firefox.com','Access-Control-Allow-Headers':'authorization,content-type','Access-Control-Allow-Methods':'POST','Access-Control-Allow-Credentials':'true'};
 await context.addCookies([{name:'oauth-fixture',value:'earned',domain:'oauth.accounts.firefox.com',path:'/',secure:true,sameSite:'None'}]);
 await page.route('https://api.accounts.firefox.com/v1/oauth/authorization',async route=>{
  const r=route.request();if(r.method()==='OPTIONS'){await route.fulfill({status:204,headers:cors});return;}
  const data=JSON.parse(r.postData());codeChallenge=data.code_challenge;codeState=data.state;
  try{
   if(!(await r.allHeaders()).cookie?.includes('signin-fixture=earned')||data.code_challenge_method!=='S256'||!codeState||!codeChallenge)throw Error('Authorization dropped cookie/state/PKCE');
   const h=Object.fromEntries([...r.headers().authorization.matchAll(/(id|ts|nonce|mac|hash)="([^"]+)"/g)].map(m=>[m[1],m[2]]));
   const key=Buffer.from(crypto.hkdfSync('sha256',Buffer.from('34'.repeat(32),'hex'),Buffer.alloc(32),'identity.mozilla.com/picl/v1/sessionToken',64));
   const hash=crypto.createHash('sha256').update('hawk.1.payload\napplication/json\n'+r.postData()+'\n').digest('base64');
   const text=`hawk.1.header\n${h.ts}\n${h.nonce}\nPOST\n/v1/oauth/authorization\napi.accounts.firefox.com\n443\n${hash}\n\n`;
   if(h.id!==key.subarray(0,32).toString('hex')||h.hash!==hash||h.mac!==crypto.createHmac('sha256',key.subarray(32)).update(text).digest('base64'))throw Error('Authorization Hawk signature invalid');
  }catch(e){exchangeError=e;}
  await route.fulfill({status:200,headers:cors,contentType:'application/json',body:JSON.stringify({code:'single-use-fixture',state:mismatch?'wrong-state':codeState})});
 });
 await page.route('https://oauth.accounts.firefox.com/v1/token',async route=>{
  const r=route.request();if(r.method()==='OPTIONS'){await route.fulfill({status:204,headers:cors});return;}
  codeCalls++;const data=JSON.parse(r.postData());
  if(!(await r.allHeaders()).cookie?.includes('oauth-fixture=earned')||r.headers().authorization||data.grant_type!=='authorization_code'||data.code!=='single-use-fixture'||crypto.createHash('sha256').update(data.code_verifier).digest('base64url')!==codeChallenge)exchangeError=Error('PKCE exchange lost cookie, verifier or code');
  await route.fulfill({status:200,headers:cors,contentType:'application/json',body:JSON.stringify({access_token:'a1'.repeat(32),refresh_token:'b2'.repeat(32),expires_in:3600})});
 });
 const until=async predicate=>{for(let n=0;n<150;n++){if(predicate())return;await new Promise(r=>setTimeout(r,20));}throw Error('Browser grant transition timed out');};
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
 await until(()=>messages.length===1);
 if(messages.length!==1||messages[0].nonce!=='fixture-nonce'||messages[0].kind!=='grant'||messages[0].access_token!=='a1'.repeat(32))throw Error('Verified handoff missing/duplicated');
 await page.evaluate(()=>window.__dicodeFoxRetry());await until(()=>messages.length===2);
 if(messages.length!==2)throw Error('Interactive retry is broken');
 await page.evaluate(()=>{
  window.__dicodeFoxWaiting();
  document.dispatchEvent(new CustomEvent('WebChannelMessageToChrome',{bubbles:true,detail:JSON.stringify({id:'account_updates',message:{command:'fxaccounts:verified',data:{sessionToken:'34'.repeat(32)},messageId:'verified'}})}));
 });await until(()=>messages.length===3);
 if(messages.length!==3||messages[2].kind!=='grant')throw Error('Rotated verification session was lost');

 if(exchangeError)throw exchangeError;
 if(exchangeCount!==3)throw Error('Missing browser-side OAuth exchanges');
 reject=true;await page.evaluate(()=>window.__dicodeFoxRetry());await until(()=>exchangeCount===4);await new Promise(r=>setTimeout(r,100));
 if(messages.length!==3||authErrors.at(-1)?.code!=='session_unconfirmed')throw Error('Unconfirmed browser grant was accepted or not explained');
 reject=false,blocked=false,mismatch=false,codeChallenge="",codeState="",codeCalls=0;await page.evaluate(()=>window.__dicodeFoxRetry());await until(()=>messages.length===4);
 if(exchangeError)throw exchangeError;
 await page.reload();await until(()=>messages.length===5);
 if(messages[4].kind!=='grant')throw Error('Full-page verification lost the pending session');
 blocked=true;await page.evaluate(()=>window.__dicodeFoxRetry());await until(()=>messages.length===6);
 if(codeCalls!==1||messages[5].kind!=='grant'||exchangeError)throw exchangeError||Error('Browser PKCE fallback failed');
 mismatch=true;await page.evaluate(()=>window.__dicodeFoxRetry());await until(()=>authErrors.at(-1)?.code==='invalid_grant');
 if(codeCalls!==1||messages.length!==6)throw Error('Mismatched OAuth state was accepted');
 const foreign=await context.newPage();let leaks=[];await foreign.exposeFunction('capture',v=>leaks.push(v));
 await foreign.addInitScript({content:"window.dicodeFox={postMessage:value=>window.capture(value)};\n"+source.replace('__DICODE_NONCE__',JSON.stringify('fixture-nonce'))});
 await foreign.route('https://foreign.invalid/**',r=>r.fulfill({status:200,contentType:'text/html',body:'<html><body>Foreign fixture</body></html>'}));await foreign.goto('https://foreign.invalid/');
 if(await foreign.evaluate(()=>!!window.__dicodeFoxHooked))throw Error('Bridge installed on foreign origin');
 if(leaks.length)throw Error('Foreign session leaked');
 const late=await context.newPage();let lateReady=false;
 await late.exposeFunction('capture',value=>{if(JSON.parse(value).kind==='bridge_ready')lateReady=true;});
 await late.route('https://accounts.firefox.com/**',r=>r.fulfill({status:200,contentType:'text/html',body:'<html><body>Late bridge fixture</body></html>'}));
 await late.goto('https://accounts.firefox.com/');
 await late.evaluate(script=>{window.dicodeFox={postMessage:v=>window.capture(v)};(0,eval)(script);},source.replace('__DICODE_NONCE__',JSON.stringify('fixture-nonce')));
 await until(()=>lateReady);
 console.log('PASS actual Chromium WebChannel: status/link replies, OTP gating, cookie-bearing signed OAuth and PKCE/state recovery, unconfirmed-grant rejection, retry, origin isolation');
 }finally{await browser.close()}})().catch(e=>{console.error(e);process.exit(1)});
