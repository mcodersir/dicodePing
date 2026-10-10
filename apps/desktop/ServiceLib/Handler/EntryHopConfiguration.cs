namespace ServiceLib.Handler;

public static class EntryHopConfiguration
{
    public const string Tag = "dicode-entry-hop";
    public static string Apply(string content, CoreConfigContext context)
    {
        if (!context.UseEntryHop) return content;
        if (context.Node.ConfigType == EConfigType.Custom)
            throw new InvalidOperationException(ResUI.DicodeEntryCustomUnsupported);
        var root = JsonNode.Parse(content) as JsonObject ?? throw new InvalidOperationException("Invalid generated configuration");
        var outbounds = root["outbounds"] as JsonArray ?? throw new InvalidOperationException("Missing outbounds");
        var port = context.AppConfig.EntryHopItem.Port;
        if (port is < 1024 or > 65535) throw new InvalidOperationException("Invalid entry-hop port");
        var count = 0;
        foreach (var outbound in outbounds.OfType<JsonObject>())
        {
            var tag = outbound["tag"]?.GetValue<string>() ?? "";
            if (!tag.StartsWith(Global.ProxyTag, StringComparison.Ordinal) && !tag.StartsWith("fragment-", StringComparison.Ordinal)) continue;
            if (context.RunCoreType == ECoreType.sing_box)
            {
                if (outbound["detour"] is not null) continue;
                outbound["detour"] = Tag;
            }
            else
            {
                var stream = outbound["streamSettings"] as JsonObject ?? new JsonObject();
                var sockopt = stream["sockopt"] as JsonObject ?? new JsonObject();
                if (sockopt["dialerProxy"] is not null) continue;
                sockopt["dialerProxy"] = Tag;
                stream["sockopt"] = sockopt;
                outbound["streamSettings"] = stream;
            }
            count++;
        }
        if (count == 0) throw new InvalidOperationException("No terminal proxy outbound for entry hop");
        outbounds.Add(context.RunCoreType == ECoreType.sing_box
            ? new JsonObject { ["type"] = "socks", ["tag"] = Tag, ["server"] = Global.Loopback, ["server_port"] = port, ["version"] = "5" }
            : new JsonObject { ["protocol"] = "socks", ["tag"] = Tag, ["settings"] = new JsonObject { ["servers"] = new JsonArray(new JsonObject { ["address"] = Global.Loopback, ["port"] = port }) } });
        return root.ToJsonString();
    }
}
