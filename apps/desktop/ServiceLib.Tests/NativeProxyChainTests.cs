using ServiceLib.Tests.CoreConfig;
using Xunit;

namespace ServiceLib.Tests;

public class NativeRuntimeTestsProxyChain
{
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task GeneratedChainCarriesHttpThroughBothHops(bool shadowsocksExit)
    {
        var root = Environment.GetEnvironmentVariable("DICODE_RUNTIME_TEST_ROOT");
        if (string.IsNullOrEmpty(root)) Assert.Skip("Requires the bundled Xray runtime.");
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var ct = deadline.Token;
        var origin = new TcpListener(IPAddress.Loopback, 0); origin.Start();
        var originPort = ((IPEndPoint)origin.LocalEndpoint).Port;
        var entryPort = Utils.GetFreePort(28000);
        var exitPort = Utils.GetFreePort(entryPort + 1);
        var clientPort = Utils.GetFreePort(exitPort + 1);
        var metricsPort = Utils.GetFreePort(clientPort + 1);
        var temp = Path.Combine(Path.GetTempPath(), "chain-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temp);
        var binary = Path.Combine(root!, "bin", "xray", "xray" + (OperatingSystem.IsWindows() ? ".exe" : ""));
        var fixture = new JsonObject {
            ["log"] = new JsonObject { ["loglevel"] = "debug" },
            ["inbounds"] = new JsonArray(
                new JsonObject { ["tag"] = "entry", ["listen"] = "127.0.0.1", ["port"] = entryPort, ["protocol"] = "socks", ["settings"] = new JsonObject { ["auth"] = "noauth" } },
                new JsonObject { ["tag"] = "exit", ["listen"] = "127.0.0.1", ["port"] = exitPort, ["protocol"] = shadowsocksExit ? "shadowsocks" : "socks", ["settings"] = shadowsocksExit ? new JsonObject { ["method"] = "aes-128-gcm", ["password"] = "chain-fixture-password", ["network"] = "tcp" } : new JsonObject { ["auth"] = "noauth" } }),
            // The test origin is local. New Xray servers block private targets
            // by default for SS; allow only this fixture's exact address/port.
            ["outbounds"] = new JsonArray(new JsonObject { ["protocol"] = "freedom", ["settings"] = new JsonObject {
                ["finalRules"] = new JsonArray(new JsonObject { ["action"] = "allow", ["ip"] = new JsonArray("127.0.0.1/32"), ["port"] = originPort.ToString() })
            } }),
            ["stats"] = new JsonObject(), ["metrics"] = new JsonObject { ["listen"] = $"127.0.0.1:{metricsPort}" },
            ["policy"] = new JsonObject { ["system"] = new JsonObject { ["statsInboundUplink"] = true, ["statsInboundDownlink"] = true } }
        };
        var config = CoreConfigTestFactory.CreateConfig();
        config.CoreBasicItem.Loglevel = "debug";
        CoreConfigTestFactory.BindAppManagerConfig(config);
        var entry = CoreConfigTestFactory.CreateSocksNode(ECoreType.Xray, "entry", "entry");
        entry.Port = entryPort; entry.Username = ""; entry.Password = "";
        var exit = CoreConfigTestFactory.CreateSocksNode(ECoreType.Xray, "exit", "exit");
        exit.Port = exitPort; exit.Username = ""; exit.Password = "";
        if (shadowsocksExit) {
            exit.ConfigType = EConfigType.Shadowsocks;
            exit.SetProtocolExtra(exit.GetProtocolExtra() with { SsMethod = "aes-128-gcm" });
            exit.Password = "chain-fixture-password";
        }
        var chain = CoreConfigTestFactory.CreateProxyChainNode(ECoreType.Xray, "chain", "chain", [entry.IndexId, exit.IndexId]);
        var context = CoreConfigTestFactory.CreateContext(config, chain, ECoreType.Xray);
        context.AllProxiesMap[entry.IndexId] = entry;
        context.AllProxiesMap[exit.IndexId] = exit;
        var generated = new CoreConfigV2rayService(context).GenerateClientSpeedtestConfig(clientPort);
        Assert.True(generated.Success, generated.Msg);
        var serverFile = Path.Combine(temp, "server.json"); var clientFile = Path.Combine(temp, "client.json");
        await File.WriteAllTextAsync(serverFile, fixture.ToJsonString(), ct);
        await File.WriteAllTextAsync(clientFile, generated.Data!.ToString(), ct);
        using var server = new ProcessService(binary, "run -c " + serverFile.AppendQuotes(), temp, true, false, null, (_, _) => Task.CompletedTask);
        using var client = new ProcessService(binary, "run -c " + clientFile.AppendQuotes(), temp, true, false, null, (_, _) => Task.CompletedTask);
        try {
            await server.StartAsync(); await client.StartAsync();
            await Task.Delay(500, ct);
            Assert.False(server.HasExited, server.RecentOutput); Assert.False(client.HasExited, client.RecentOutput);
            var response = Task.Run(async () => {
                using var connection = await origin.AcceptTcpClientAsync(ct);
                using var stream = connection.GetStream();
                using var reader = new StreamReader(stream, leaveOpen: true);
                Assert.StartsWith("GET /chain-proof ", await reader.ReadLineAsync(ct));
                while (!string.IsNullOrEmpty(await reader.ReadLineAsync(ct))) { }
                await stream.WriteAsync(Encoding.ASCII.GetBytes("HTTP/1.1 200 OK\r\nContent-Length: 8\r\nConnection: close\r\n\r\nchain-ok"), ct);
            });
            using var http = new HttpClient(new SocketsHttpHandler { Proxy = new WebProxy($"http://127.0.0.1:{clientPort}"), UseProxy = true });
            Assert.Equal("chain-ok", await http.GetStringAsync($"http://127.0.0.1:{originPort}/chain-proof", ct));
            await response;
            using var direct = new HttpClient(new SocketsHttpHandler { UseProxy = false });
            var metrics = JsonNode.Parse(await direct.GetStringAsync($"http://127.0.0.1:{metricsPort}/debug/vars", ct))!;
            foreach (var hop in new[] { "entry", "exit" }) {
                Assert.True(metrics["stats"]!["inbound"]![hop]!["uplink"]!.GetValue<long>() > 0, hop);
            }
        } catch (Exception e) { throw new InvalidOperationException("Server: " + server.RecentOutput + "\nClient: " + client.RecentOutput + "\nConfig: " + generated.Data, e); }
        finally {
            await client.StopAsync(); await server.StopAsync(); origin.Stop(); Directory.Delete(temp, true);
        }
    }
}
