// Firefox Accounts WebChannel integration; native OAuth recovery uses Arman VPN v1.0.11 (GPL-3.0).
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
 const body=JSON.stringify({client_id:'5882386c6d801776',grant_type:'fxa-credentials',scope:'profile https://identity.mozilla.com/apps/vpn',access_type:'offline'});
 const hash=base64(await crypto.subtle.digest('SHA-256',bytes('hawk.1.payload\napplication/json\n'+body+'\n')));
 const ts=String(Math.floor(Date.now()/1000));
 const random=crypto.getRandomValues(new Uint8Array(6));
 const requestNonce=base64(random).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
 const normalized='hawk.1.header\n'+ts+'\n'+requestNonce+'\nPOST\n/v1/oauth/token\napi.accounts.firefox.com\n443\n'+hash+'\n\n';
 const mac=base64(await hmac(key,bytes(normalized)));
 const hex=Array.from(id,b=>b.toString(16).padStart(2,'0')).join('');
 const authorization='Hawk id="'+hex+'", ts="'+ts+'", nonce="'+requestNonce+'", mac="'+mac+'", hash="'+hash+'"';
 const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),20000);
 try {
  const response=await fetch('https://api.accounts.firefox.com/v1/oauth/token',{method:'POST',headers:{Authorization:authorization,'Content-Type':'application/json'},body:body,signal:controller.signal});
  const grant=await response.json();
  if(!response.ok){if(grant.errno===104){inFlight=false;return;}throw Error('exchange_rejected');}
  const valid=x=>typeof x==='string'&&/^[A-Za-z0-9._~+\/-]{16,2048}$/.test(x);
  if(!valid(grant.access_token)||(grant.refresh_token!=null&&!valid(grant.refresh_token))||!Number.isSafeInteger(grant.expires_in)||grant.expires_in<=0||grant.expires_in>31536000)throw Error('invalid_grant');
  if(session!==token || accountEmail!==email)return;
  post({kind:'grant',access_token:grant.access_token,refresh_token:grant.refresh_token||null,expires_in:grant.expires_in});
 }finally{clearTimeout(timeout);}
}
function sendSession(){
 if(inFlight || !/^[a-f0-9]{64}$/i.test(token) || !email || location.origin!=='https://accounts.firefox.com')return;
 inFlight=true;
 const session=token,accountEmail=email;
 browserGrant(session,accountEmail).catch(()=>{
  // Use the native Arman OAuth code/PKCE recovery when WebCrypto, CORS or direct token exchange fails.
  // Do not print response bodies, tokens, cookies, or request headers.
  if(session===token && accountEmail===email)post({kind:'session',session_token:session});
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
document.addEventListener('DOMContentLoaded',()=>post({kind:'bridge_ready'}),{once:true});
})();
