using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Threading;
using NativeWebView.Core;
using ServiceLib.Services;
using System.Text.Json;

public static class Program
{
 [STAThread]
 public static void Main(string[] args) => AppBuilder.Configure<BrowserSmokeApp>().UsePlatformDetect().StartWithClassicDesktopLifetime(args);
}

public sealed class BrowserSmokeApp : Application
{
 public override void OnFrameworkInitializationCompleted()
 {
  if (ApplicationLifetime is not IClassicDesktopStyleApplicationLifetime life) return;
  var nonce = Guid.NewGuid().ToString("N");
  if (OperatingSystem.IsWindows()) NativeWebView.Platform.Windows.NativeWebViewPlatformWindowsModule.RegisterDefault();
  else if (OperatingSystem.IsMacOS()) NativeWebView.Platform.macOS.NativeWebViewPlatformMacOSModule.RegisterDefault();
  else NativeWebView.Platform.Linux.NativeWebViewPlatformLinuxModule.RegisterDefault();
  var web = new NativeWebView.Controls.NativeWebView();
  web.InstanceConfiguration.ControllerOptions.IsInPrivateModeEnabled=true;
  web.InstanceConfiguration.ControllerOptions.IsPasswordAutosaveEnabled=false;
  web.InstanceConfiguration.DocumentStartScripts.Add(new NativeWebViewDocumentStartScript(FoxBrowserProtocol.Script(nonce),NativeWebViewScriptFrameScope.MainFrame));
  // Test-only in-memory responses: no request reaches the real Mozilla service.
  web.WebResourceRequested += (_,e)=>{
   e.Handled=true;e.StatusCode=200;
   if(e.Uri?.AbsolutePath=="/v1/session/verify_code"){e.ContentType="application/json";e.ResponseBody="{}";return;}
   e.ContentType="text/html";e.ResponseBody="""
    <!doctype html><html><body><h1>Local WebChannel integration fixture</h1><script>
    let replied=false;
    function read(e){try{let d=typeof e.detail==='string'?JSON.parse(e.detail):e.detail;if(d.message.command==='fxaccounts:fxa_status')replied=true;}catch(_){}}
    window.addEventListener('WebChannelMessageToContent',read);
    document.addEventListener('WebChannelMessageToContent',read);
    function message(command,data,id){document.dispatchEvent(new CustomEvent('WebChannelMessageToChrome',{bubbles:true,detail:JSON.stringify({id:'account_updates',message:{command:command,data:data,messageId:id}})}));}
    window.addEventListener('load',async()=>{
     message('fxaccounts:fxa_status',{},'status');
     message('fxaccounts:can_link_account',{},'link');
     if(!replied)throw Error('Status reply missing');
     message('fxaccounts:login',{email:'fixture@example.test',sessionToken:'1212121212121212121212121212121212121212121212121212121212121212',verified:false},'login');
     await fetch('/v1/session/verify_code',{method:'POST'});
    });
    </script></body></html>
    """;
  };
  var window=new Window{Width=640,Height=720,Content=web};life.MainWindow=window;
  bool finished=false;
  void Finish(int code,string message){if(finished)return;finished=true;Console.WriteLine(message);web.Dispose();life.Shutdown(code);}
  web.WebMessageReceived+=(_,e)=>Dispatcher.UIThread.Post(()=>{
   var payload=e.Message??e.Json;
   if(payload?.StartsWith('"')==true)payload=JsonSerializer.Deserialize<string>(payload);
   var session=FoxBrowserProtocol.Parse(web.CurrentUrl?.ToString(),payload,nonce);
   if(session is null){Finish(2,"FAIL native origin/session contract");return;}
   Finish(0,"PASS actual native browser: document-start WebChannel, status reply, OTP completion, private session handoff");
  });
  window.Opened+=async(_,_)=>{
   try{await web.InitializeAsync();web.Navigate("https://accounts.firefox.com/dicode-local-fixture");}
   catch(Exception e){Finish(3,"FAIL native browser initialization: "+e.GetType().Name+": "+e.Message);}
  };
  var timer=new DispatcherTimer{Interval=TimeSpan.FromSeconds(45)};
  timer.Tick+=(_,_)=>Finish(4,"FAIL native browser handoff timed out");timer.Start();
  base.OnFrameworkInitializationCompleted();
 }
}
