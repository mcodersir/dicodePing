using Xunit;
namespace ServiceLib.Tests;
public class DownloadLifecycleTests
{
 [Fact] public async Task SlowSubscriptionResponseIsNotRetriedOrDiscardedAtOldTenSecondDeadline()
 {
  using var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
  var port=((IPEndPoint)listener.LocalEndpoint).Port;
  var serve=Task.Run(async()=> {
   using var peer=await listener.AcceptTcpClientAsync(); using var stream=peer.GetStream();
   var buffer=new byte[4096]; await stream.ReadAsync(buffer);
   await Task.Delay(TimeSpan.FromSeconds(11));
   await stream.WriteAsync(Encoding.ASCII.GetBytes("HTTP/1.1 200 OK\r\nContent-Length: 15\r\nConnection: close\r\n\r\nsubscription-ok"));
  });
  using var deadline=new CancellationTokenSource(TimeSpan.FromSeconds(20));
  var service=new DownloadService();
  var result=await service.TryDownloadString($"http://127.0.0.1:{port}/subscription",(IWebProxy?)null,"DicodeTest",deadline.Token);
  Assert.Equal("subscription-ok",result); await serve; Assert.False(listener.Pending());
 }
 [Fact] public async Task ExplicitUserCancellationDoesNotBecomeInvalidSubscriptionOrStartFallback()
 {
  using var canceled=new CancellationTokenSource(); canceled.Cancel();
  await Assert.ThrowsAnyAsync<OperationCanceledException>(()=>new DownloadService().TryDownloadString("http://127.0.0.1:1/sub",(IWebProxy?)null,"DicodeTest",canceled.Token));
 }
}
