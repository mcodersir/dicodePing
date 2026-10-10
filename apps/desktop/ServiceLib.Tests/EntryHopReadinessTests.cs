using Xunit;

namespace ServiceLib.Tests;

public class EntryHopReadinessTests
{
    [Fact]
    public async Task AnOpenLocalPortAloneIsNotReadiness()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
        using var cancellation = new CancellationTokenSource(TimeSpan.FromSeconds(3));
        var accept = Task.Run(async () => { using var socket = await listener.AcceptTcpClientAsync(cancellation.Token); });
        try {
            await Assert.ThrowsAnyAsync<Exception>(() => EntryHopService.ProbeAsync(((IPEndPoint)listener.LocalEndpoint).Port, "http://example.test/generate_204", cancellation.Token));
            await accept;
        } finally { listener.Stop(); }
    }

    [Fact]
    public async Task ReadinessRequiresARequestThroughTheSocksProxy()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start();
        using var cancellation = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var received = "";
        var serve = Task.Run(async () => {
            using var socket = await listener.AcceptTcpClientAsync(cancellation.Token);
            var stream = socket.GetStream();
            var greeting = new byte[2]; await stream.ReadExactlyAsync(greeting, cancellation.Token);
            await stream.ReadExactlyAsync(new byte[greeting[1]], cancellation.Token);
            await stream.WriteAsync(new byte[] { 5, 0 }, cancellation.Token);
            var request = new byte[4]; await stream.ReadExactlyAsync(request, cancellation.Token);
            Assert.Equal(3, request[3]);
            var length = new byte[1]; await stream.ReadExactlyAsync(length, cancellation.Token);
            var destination = new byte[length[0]]; await stream.ReadExactlyAsync(destination, cancellation.Token);
            Assert.Equal("example.test", Encoding.ASCII.GetString(destination));
            await stream.ReadExactlyAsync(new byte[2], cancellation.Token);
            await stream.WriteAsync(new byte[] { 5, 0, 0, 1, 127, 0, 0, 1, 0, 0 }, cancellation.Token);
            var buffer = new byte[1]; var header = new StringBuilder();
            while (!header.ToString().EndsWith("\r\n\r\n")) { await stream.ReadExactlyAsync(buffer, cancellation.Token); header.Append((char)buffer[0]); }
            received = header.ToString();
            await stream.WriteAsync(Encoding.ASCII.GetBytes("HTTP/1.1 204 No Content\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"), cancellation.Token);
        });
        try {
            var delay = await EntryHopService.ProbeAsync(((IPEndPoint)listener.LocalEndpoint).Port, "http://example.test/generate_204", cancellation.Token);
            await serve;
            Assert.True(delay > 0); Assert.Contains("GET /generate_204", received);
        } finally { listener.Stop(); }
    }
}
