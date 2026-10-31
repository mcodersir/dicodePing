package com.v2ray.ang.core

import android.webkit.WebView
import android.webkit.WebViewClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.net.Uri
import androidx.test.core.app.ActivityScenario
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import com.v2ray.ang.ui.main.MainActivity
import org.json.JSONObject
import org.junit.Assert.*
import java.io.ByteArrayInputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

internal object BrowserBridgeFixture {
 fun exercise() {
  val latch=CountDownLatch(1);val pending=AtomicBoolean(false);val sessions=AtomicInteger(0)
  var failure:String?=null
  val nonce="android-native-fixture";val token="12".repeat(32)
  ActivityScenario.launch(MainActivity::class.java).use { scenario ->
   var browser:WebView?=null
   scenario.onActivity { activity ->
    assertTrue("System WebView lacks origin-bound messaging",WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER))
    val view=WebView(activity);browser=view;activity.setContentView(view)
    view.settings.javaScriptEnabled=true;view.settings.domStorageEnabled=true
    val script=activity.assets.open("fox-browser.js").bufferedReader().use{it.readText()}.replace("__DICODE_NONCE__",JSONObject.quote(nonce))
    WebViewCompat.addWebMessageListener(view,"dicodeFox",setOf("https://accounts.firefox.com")){_,message,origin,mainFrame,_->
     if(mainFrame && origin.scheme=="https" && origin.host=="accounts.firefox.com"){
      val data=JSONObject(message.data ?: "{}")
      when(data.optString("kind")){
       "otp-pending"->pending.set(true)
       "session"->{
        if(!pending.get()||data.optString("nonce")!=nonce||data.optString("session_token")!=token)failure="Premature/untrusted session handoff"
        sessions.incrementAndGet();latch.countDown()
       }
      }
     }
    }
    val documentStart=WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)
    if(documentStart)WebViewCompat.addDocumentStartJavaScript(view,script,setOf("https://accounts.firefox.com"))
    val html="""<!doctype html><html><body><h1>Local WebChannel fixture</h1><script>
      var statusReplied=false;
      window.addEventListener('WebChannelMessageToContent',function(e){try{var d=typeof e.detail==='string'?JSON.parse(e.detail):e.detail;if(d.message.command==='fxaccounts:fxa_status')statusReplied=true;}catch(_){}});
      function msg(command,data,id){document.dispatchEvent(new CustomEvent('WebChannelMessageToChrome',{bubbles:true,detail:JSON.stringify({id:'account_updates',message:{command:command,data:data,messageId:id}})}));}
      window.addEventListener('load',async function(){
        msg('fxaccounts:fxa_status',{},'status');msg('fxaccounts:can_link_account',{},'link');
        if(!statusReplied)return;
        msg('fxaccounts:login',{email:'fixture@example.test',sessionToken:'$token',verified:false},'login');
        dicodeFox.postMessage(JSON.stringify({kind:'otp-pending'}));
        await fetch('/v1/session/verify_code',{method:'POST'});
      });
      </script></body></html>"""
    view.webViewClient=object:WebViewClient(){
     override fun shouldInterceptRequest(v:WebView,request:WebResourceRequest):WebResourceResponse{
      val verify=request.url.path=="/v1/session/verify_code"
      return WebResourceResponse(if(verify)"application/json" else "text/html","UTF-8",ByteArrayInputStream((if(verify)"{}" else html).toByteArray()))
     }
     override fun onPageStarted(v:WebView,url:String?,icon:android.graphics.Bitmap?){if(!documentStart)v.evaluateJavascript(script,null)}
    }
    view.loadUrl("https://accounts.firefox.com/dicode-local-fixture")
   }
   try{assertTrue("Native Android WebChannel/OTP handoff timed out",latch.await(30,TimeUnit.SECONDS));assertNull(failure);assertEquals(1,sessions.get())}
   finally{scenario.onActivity{browser?.stopLoading();browser?.destroy()}}
  }
 }
}
