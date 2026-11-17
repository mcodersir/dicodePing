using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Cryptography.X509Certificates;
using System.Text;

// Isolated CI-only HTTPS origin through the same HTTP proxy configuration as
// production. No resource interception or external account service is involved.
internal sealed class LinuxBrowserFixture : IDisposable
{
    private readonly TcpListener listener = new(IPAddress.Loopback, 0);
    private readonly CancellationTokenSource stop = new();
    private readonly X509Certificate2 certificate = X509Certificate2.CreateFromPemFile(
        "/tmp/dicode-browser-fixture/leaf.crt", "/tmp/dicode-browser-fixture/leaf.key");
    public string Html { get; set; } = "";
    public string Address => "127.0.0.1:" + ((IPEndPoint)listener.LocalEndpoint).Port;
    public LinuxBrowserFixture() { listener.Start(); _ = AcceptAsync(); }
    private async Task AcceptAsync()
    {
        try { while (!stop.IsCancellationRequested) { var socket = await listener.AcceptTcpClientAsync(stop.Token); _ = ServeAsync(socket); } }
        catch (OperationCanceledException) { }
    }
    private static async Task<string> Headers(Stream stream, CancellationToken token)
    {
        var bytes = new List<byte>(); var one = new byte[1];
        while (bytes.Count < 16384) {
            if (await stream.ReadAsync(one, token) == 0) throw new IOException("Fixture request closed");
            bytes.Add(one[0]);
            if (bytes.Count >= 4 && bytes[^4] == 13 && bytes[^3] == 10 && bytes[^2] == 13 && bytes[^1] == 10)
                return Encoding.ASCII.GetString(bytes.ToArray());
        }
        throw new IOException("Fixture header is too long");
    }
    private async Task ServeAsync(TcpClient socket)
    {
        using (socket) try {
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(stop.Token); deadline.CancelAfter(TimeSpan.FromSeconds(20));
            var token = deadline.Token; var transport = socket.GetStream();
            var connect = await Headers(transport, token);
            if (!connect.StartsWith("CONNECT accounts.firefox.com:443 ", StringComparison.Ordinal)) throw new IOException("Unexpected fixture target");
            await transport.WriteAsync("HTTP/1.1 200 Connection Established\r\n\r\n"u8.ToArray(), token);
            using var tls = new SslStream(transport, false);
            await tls.AuthenticateAsServerAsync(new SslServerAuthenticationOptions { ServerCertificate = certificate }, token);
            var request = await Headers(tls, token);
            if (request.Contains("/dicode-intentional-failure")) return;
            var json = request.StartsWith("POST /v1/session/verify_code ");
            var body = Encoding.UTF8.GetBytes(json ? "{}" : Html);
            var header = Encoding.ASCII.GetBytes($"HTTP/1.1 200 OK\r\nContent-Type: {(json ? "application/json" : "text/html; charset=utf-8")}\r\nContent-Length: {body.Length}\r\nConnection: close\r\n\r\n");
            await tls.WriteAsync(header, token); await tls.WriteAsync(body, token); await tls.FlushAsync(token);
        } catch (Exception error) when (error is IOException or OperationCanceledException or System.Security.Authentication.AuthenticationException) { }
    }
    public void Dispose() { stop.Cancel(); listener.Stop(); certificate.Dispose(); }
}
