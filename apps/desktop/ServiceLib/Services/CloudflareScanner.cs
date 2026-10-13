using System.Net.Security;

namespace ServiceLib.Services;

public sealed record CloudflareScanResult(string Address, long? Latency, string? Error);

/// <summary>Bounded HTTPS reachability scan of user-supplied edge IPs. TCP alone is not a success.</summary>
public static class CloudflareScanner
{
    public static async Task<List<CloudflareScanResult>> ScanAsync(IEnumerable<string> addresses,
        Action<int, int>? progress, CancellationToken token)
    {
        var ips = addresses.Select(x => x.Trim()).Where(x => x.Length > 0).Distinct().ToList();
        if (ips.Count > 1024) throw new ArgumentException("Maximum 1024 IP addresses per scan");
        if (ips.Any(x => !IPAddress.TryParse(x, out _))) throw new ArgumentException("Supply IP addresses, one per line");
        var results = new ConcurrentBag<CloudflareScanResult>();
        var completed = 0;
        await Parallel.ForEachAsync(ips, new ParallelOptions { MaxDegreeOfParallelism = 8, CancellationToken = token }, async (ip, ct) => {
            try
            {
                using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
                deadline.CancelAfter(TimeSpan.FromSeconds(8));
                using var socket = new TcpClient(IPAddress.Parse(ip).AddressFamily);
                var watch = Stopwatch.StartNew();
                await socket.ConnectAsync(IPAddress.Parse(ip), 443, deadline.Token);
                await using var tls = new SslStream(socket.GetStream());
                await tls.AuthenticateAsClientAsync(new SslClientAuthenticationOptions { TargetHost = "www.cloudflare.com" }, deadline.Token);
                var request = Encoding.ASCII.GetBytes("GET /cdn-cgi/trace HTTP/1.1\r\nHost: www.cloudflare.com\r\nConnection: close\r\n\r\n");
                await tls.WriteAsync(request, deadline.Token);
                using var reader = new StreamReader(tls, Encoding.ASCII);
                var status = await reader.ReadLineAsync(deadline.Token);
                if (status is null || !status.Contains(" 200 ")) throw new IOException("HTTPS trace request failed");
                // A real HTTPS response from the certificate-validated edge is required.
                results.Add(new(ip, Math.Max(1, watch.ElapsedMilliseconds), null));
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
            catch (Exception e) { results.Add(new(ip, null, e is OperationCanceledException ? "Timeout" : e.GetType().Name)); }
            finally { progress?.Invoke(Interlocked.Increment(ref completed), ips.Count); }
        });
        return results.OrderBy(x => x.Latency is null).ThenBy(x => x.Latency).ToList();
    }
}
