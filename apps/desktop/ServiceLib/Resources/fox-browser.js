// Firefox Accounts WebChannel integration; native OAuth recovery uses Arman VPN v1.0.12 (GPL-3.0).
(function(){
'use strict';
if (window!==window.top || location.origin!=='https://accounts.firefox.com' || window.__dicodeFoxHooked) return;
window.__dicodeFoxHooked=true;
const nonce=__DICODE_NONCE__;
let token='',email='',inFlight=false;
const seen=new WeakSet();
function post(payload){
 const value=JSON.stringify(Object.assign({nonce:nonce,email:email},payload));
 if(window.dicodeFox && typeof window.dicodeFox.postMessage==='function')window.dicodeFox.postMessage(value);
 else if(window.chrome&&window.chrome.webview)window.chrome.webview.postMessage(value);
}
const bytes=s=>new TextEncoder().encode(s);
const base64=b=>btoa(String.fromCharCode(...new Uint8Array(b)));
async function hmac(key,data){
 const k=await crypto.subtle.importKey('raw',key,{name:'HMAC',hash:'SHA-256'},false,['sign']);
 return new Uint8Array(await crypto.subtle.sign('HMAC',k,data));
}
function concat(...arrays){const out=new Uint8Array(arrays.reduce((n,a)=>n+a.length,0));let i=0;for(const a of arrays){out.set(a,i);i+=a.length;}return out;}
async function browserGrant(session,accountEmail){
 // FxA's standard Hawk exchange stays in the browser that completed sign-in.
 // Fixed Mozilla endpoint; never accept a URL or auth header from page messages.
 const raw=new Uint8Array(session.match(/../g).map(x=>parseInt(x,16)));
 const prk=await hmac(new Uint8Array(32),raw),info=bytes('identity.mozilla.com/picl/v1/sessionToken');
 const id=await hmac(prk,concat(info,new Uint8Array([1])));
 const key=await hmac(prk,concat(id,info,new Uint8Array([2])));
 const hex=Array.from(id,b=>b.toString(16).padStart(2,'0')).join('');
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),60000);
 const request=async (target,data,signed)=>{
  const body=JSON.stringify(data),headers={'Content-Type':'application/json'};
  if(signed){
   const u=new URL(target),hash=base64(await crypto.subtle.digest('SHA-256',bytes('hawk.1.payload\napplication/json\n'+body+'\n')));
   const ts=String(Math.floor(Date.now()/1000));
   const requestNonce=base64(crypto.getRandomValues(new Uint8Array(6))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
   const normalized='hawk.1.header\n'+ts+'\n'+requestNonce+'\nPOST\n'+u.pathname+'\n'+u.hostname+'\n443\n'+hash+'\n\n';
   const mac=base64(await hmac(key,bytes(normalized)));
   headers.Authorization='Hawk id="'+hex+'", ts="'+ts+'", nonce="'+requestNonce+'", mac="'+mac+'", hash="'+hash+'"';
  }
  // Keep OAuth in the browser that signed in, including its earned cookies.
  const response=await fetch(target,{method:'POST',headers,body,credentials:'include',signal:controller.signal});
  let dataOut;try{dataOut=await response.json();}catch(_){dataOut={};}
  return {response,data:dataOut};
 };
 const error=code=>Object.assign(Error(code),{code});
 const client_id='5882386c6d801776',scope='profile https://identity.mozilla.com/apps/vpn';
 try {
  let result=await request('https://api.accounts.firefox.com/v1/oauth/token',{client_id,grant_type:'fxa-credentials',scope,access_type:'offline'},true);
  if(!result.response.ok&&result.data.errno===104){inFlight=false;post({kind:'auth_error',code:'session_unconfirmed'});return;}
  if([401,406].includes(result.response.status)){
   // Standard authorization-code recovery also stays in this browser.
   const url64=value=>base64(value).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
   const verifier=url64(crypto.getRandomValues(new Uint8Array(32))),state=url64(crypto.getRandomValues(new Uint8Array(24)));
   const challenge=url64(await crypto.subtle.digest('SHA-256',bytes(verifier)));
   const auth=await request('https://api.accounts.firefox.com/v1/oauth/authorization',{client_id,response_type:'code',scope,state,access_type:'offline',code_challenge:challenge,code_challenge_method:'S256'},true);
   if(!auth.response.ok)throw error(auth.data.errno===104?'session_unconfirmed':auth.response.status===406?'verification_required':'login_required');
   if(typeof auth.data.code!=='string'||!auth.data.code||auth.data.state!==state)throw error('invalid_grant');
   result=await request('https://oauth.accounts.firefox.com/v1/token',{client_id,grant_type:'authorization_code',code:auth.data.code,code_verifier:verifier},false);
  }
  if(!result.response.ok)throw error(result.data.errno===104?'session_unconfirmed':result.response.status===406?'verification_required':'login_required');
  const grant=result.data;
  const valid=x=>typeof x==='string'&&/^[A-Za-z0-9._~+\/-]{16,2048}$/.test(x);
  if(!valid(grant.access_token)||(grant.refresh_token!=null&&!valid(grant.refresh_token))||!Number.isSafeInteger(grant.expires_in)||grant.expires_in<=0||grant.expires_in>31536000)throw error('invalid_grant');
  if(session!==token || accountEmail!==email)return;
  post({kind:'grant',access_token:grant.access_token,refresh_token:grant.refresh_token||null,expires_in:grant.expires_in});
 }finally{clearTimeout(timeout);}
}

function sendSession(){
 if(inFlight || !/^[a-f0-9]{64}$/i.test(token) || !email || location.origin!=='https://accounts.firefox.com')return;
 inFlight=true;
 post({kind:'auth_progress'});
 const session=token,accountEmail=email;
 browserGrant(session,accountEmail).catch(error=>{
  if(session!==token || accountEmail!==email)return;
  inFlight=false;
  // A browser rejection is a real error, not an invitation to repeat the
  // same rejected session in another client for another 100 seconds.
  post({kind:'auth_error',code:['session_unconfirmed','verification_required','login_required','invalid_grant'].includes(error.code)?error.code:'network'});
 });
}
window.__dicodeFoxRetry=function(){inFlight=false;sendSession();};
window.__dicodeFoxWaiting=function(){inFlight=false;};
function reply(id,command,data){
 const env={id:'account_updates',message:{messageId:id,command:command,data:data}};
 for(const target of [window,document])for(const detail of [env,JSON.stringify(env)])target.dispatchEvent(new CustomEvent('WebChannelMessageToContent',{detail:detail}));
}
function message(event){
 if(seen.has(event))return;seen.add(event);
 try{
  const envelope=typeof event.detail==='string'?JSON.parse(event.detail):event.detail;
  if(!envelope||envelope.id!=='account_updates')return;
  const m=envelope.message||{},d=m.data||{},cmd=m.command;
  if(cmd==='fxaccounts:fxa_status')reply(m.messageId,cmd,{capabilities:{},signedInUser:null});
  else if(cmd==='fxaccounts:can_link_account')reply(m.messageId,cmd,{ok:true});
  else if(cmd==='fxaccounts:login'||cmd==='fxaccounts:oauth_login'){
   const value=String(d.sessionToken||d.token||'').trim();
   if(/^[a-f0-9]{64}$/i.test(value)){if(value!==token)inFlight=false;token=value;email=String(d.email||'').trim();post({kind:'pending_session',session_token:token});if(d.verified!==false && !d.verificationReason)sendSession();}
   if(m.messageId)reply(m.messageId,cmd,{ok:true});
  }else if(typeof cmd==='string'&&cmd.includes('verified')){
   const value=String(d.sessionToken||d.token||'').trim();
   if(/^[a-f0-9]{64}$/i.test(value)){if(value!==token)inFlight=false;token=value;}
   if(typeof d.email==='string'&&d.email.trim())email=d.email.trim();
   post({kind:'pending_session',session_token:token});sendSession();
  }
 }catch(_){}
}
window.addEventListener('WebChannelMessageToChrome',message);
document.addEventListener('WebChannelMessageToChrome',message);
function isVerify(address){
 try{const u=new URL(typeof address==='string'?address:address.url,location.href);return u.protocol==='https:'&&['accounts.firefox.com','api.accounts.firefox.com'].includes(u.hostname)&&/\/(verify|verify_code|totp)(\/|$)/.test(u.pathname);}catch(_){return false;}
}
if(window.fetch){const old=window.fetch;window.fetch=function(...args){return old.apply(this,args).then(r=>{if(r.ok&&isVerify(args[0]))sendSession();return r;});};}
const open=XMLHttpRequest.prototype.open,send=XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.open=function(method,url,...rest){this.__dicodeVerify=isVerify(url);return open.call(this,method,url,...rest);};
XMLHttpRequest.prototype.send=function(...args){this.addEventListener('load',()=>{if(this.__dicodeVerify&&this.status>=200&&this.status<300)sendSession();});return send.apply(this,args);};
function navigated(){if(/^\/(signin\/confirmed|signup\/confirmed|connect_another_device|pair|settings|complete)(_|\/|$)/.test(location.pathname))sendSession();}
for(const name of ['pushState','replaceState']){const old=history[name];history[name]=function(...args){const r=old.apply(this,args);navigated();return r;};}
window.addEventListener('popstate',navigated);window.addEventListener('hashchange',navigated);
window.__dicodeFoxRestore=function(session,accountEmail){
 if(token || !/^[a-f0-9]{64}$/i.test(session) || typeof accountEmail!=='string' || !accountEmail.includes('@'))return;
 token=session;email=accountEmail;navigated();
};
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>post({kind:'bridge_ready'}),{once:true});else post({kind:'bridge_ready'});
})();
