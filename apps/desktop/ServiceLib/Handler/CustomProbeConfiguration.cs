namespace ServiceLib.Handler;

/// <summary>Creates an isolated listener; leaves the user's file and outbound chain untouched.</summary>
public static class CustomProbeConfiguration
{
    public static string Build(string content, ECoreType core, int port)
    {
        if (core is not (ECoreType.Xray or ECoreType.sing_box)) throw new NotSupportedException("Custom probes require Xray or sing-box JSON");
        var root = JsonNode.Parse(content) as JsonObject ?? throw new InvalidOperationException("Invalid custom JSON");
        var outbounds = root["outbounds"] as JsonArray ?? throw new InvalidOperationException("Missing custom outbounds");
        var target = outbounds.OfType<JsonObject>().FirstOrDefault(x => x["tag"]?.ToString() == Global.ProxyTag)
            ?? outbounds.OfType<JsonObject>().FirstOrDefault(x => (x[core == ECoreType.Xray ? "protocol" : "type"]?.ToString() ?? "") is not ("freedom" or "blackhole" or "dns" or "direct" or "block"));
        if (target is null) throw new InvalidOperationException("Custom profile has no proxy outbound");
        target["tag"] ??= "dicode-custom-exit";
        const string inbound = "dicode-custom-probe";
        root.Remove("api");
        root["inbounds"] = new JsonArray(core == ECoreType.Xray
            ? new JsonObject { ["tag"] = inbound, ["listen"] = Global.Loopback, ["port"] = port, ["protocol"] = "socks", ["settings"] = new JsonObject { ["auth"] = "noauth", ["udp"] = false } }
            : new JsonObject { ["tag"] = inbound, ["listen"] = Global.Loopback, ["listen_port"] = port, ["type"] = "socks" });
        var routeKey = core == ECoreType.Xray ? "routing" : "route";
        var route = root[routeKey] as JsonObject ?? new JsonObject();
        var rules = route["rules"] as JsonArray ?? new JsonArray();
        rules.Insert(0, core == ECoreType.Xray
            ? new JsonObject { ["type"] = "field", ["inboundTag"] = new JsonArray(inbound), ["outboundTag"] = target["tag"]!.ToString() }
            : new JsonObject { ["inbound"] = new JsonArray(inbound), ["action"] = "route", ["outbound"] = target["tag"]!.ToString() });
        route["rules"] = rules; root[routeKey] = route;
        return root.ToJsonString();
    }
}
