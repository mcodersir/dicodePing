namespace ServiceLib.Handler;

/// <summary>Creates an isolated listener; leaves the user's file and outbound chain untouched.</summary>
public static class CustomProbeConfiguration
{
    public static string Build(string content, ECoreType core, int port)
    {
        if (core is not (ECoreType.Xray or ECoreType.sing_box)) throw new NotSupportedException("Custom probes require Xray or sing-box JSON");
        var root = JsonNode.Parse(content) as JsonObject ?? throw new InvalidOperationException("Invalid custom JSON");
        if (core == ECoreType.Xray && CoreConfigHandler.IsServerless(root))
        {
            var source = (root["inbounds"] as JsonArray)?.OfType<JsonObject>()
                .FirstOrDefault(i => i["protocol"]?.ToString() is "mixed" or "socks")
                ?? throw new InvalidOperationException("Serverless profile has no local listener");
            var listener = source.DeepClone().AsObject();
            listener["listen"] = Global.Loopback;
            listener["port"] = port;
            root["inbounds"] = new JsonArray(listener);
            root.Remove("api");
            FakeDnsPolicy.Apply(root);
            return root.ToJsonString();
        }
        var outbounds = (root["outbounds"] as JsonArray)?.OfType<JsonObject>() ?? [];
        if (core == ECoreType.sing_box)
            outbounds = outbounds.Concat((root["endpoints"] as JsonArray)?.OfType<JsonObject>() ?? []);
        var target = outbounds.FirstOrDefault(x => x["tag"]?.ToString() == Global.ProxyTag)
            ?? outbounds.FirstOrDefault(x => (x[core == ECoreType.Xray ? "protocol" : "type"]?.ToString() ?? "") is not ("freedom" or "blackhole" or "dns" or "direct" or "block"));
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
