namespace ServiceLib.Services;

public static class NativeProfileTemplates
{
    public static string Build(string kind, string server, int port, string username, string password, string extra = "")
    {
        if (kind != "socks") throw new NotSupportedException(ResUI.DicodeRemovedCore);
        if (string.IsNullOrWhiteSpace(server) || port is < 1 or > 65535) throw new ArgumentException("Server and valid port are required");
        var remote = new JsonObject { ["address"] = server.Trim(), ["port"] = port };
        if (!string.IsNullOrEmpty(username)) remote["users"] = new JsonArray(new JsonObject { ["user"] = username, ["pass"] = password });
        return new JsonObject {
            ["inbounds"] = new JsonArray(new JsonObject { ["protocol"] = "mixed", ["tag"] = "socks", ["listen"] = "127.0.0.1", ["port"] = 1080, ["settings"] = new JsonObject { ["auth"] = "noauth", ["udp"] = true } }),
            ["outbounds"] = new JsonArray(new JsonObject { ["protocol"] = "socks", ["tag"] = "proxy", ["settings"] = new JsonObject { ["servers"] = new JsonArray(remote) } })
        }.ToJsonString();
    }
}
