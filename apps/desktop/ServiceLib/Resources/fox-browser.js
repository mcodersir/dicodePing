// Firefox Accounts WebChannel integration; native OAuth recovery uses Arman VPN v1.0.13 (GPL-3.0).
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
function sendSession(){
 if(inFlight || !/^[a-f0-9]{64}$/i.test(token) || !email || location.origin!=='https://accounts.firefox.com')return;
 inFlight=true;
 post({kind:'auth_progress'});
 const session=token,accountEmail=email;
 post({kind:'session',session_token:session});
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
   if(/^[a-f0-9]{64}$/i.test(value)){if(value!==token)inFlight=false;token=value;email=String(d.email||'').trim();post({kind:'pending_session',session_token:token});sendSession();}
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
