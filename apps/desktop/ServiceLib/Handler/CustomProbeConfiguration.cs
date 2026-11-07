namespace ServiceLib.Handler;

/// <summary>Creates an isolated listener; leaves the user's file and outbound chain untouched.</summary>
public static class CustomProbeConfiguration
{
    public static string Build(string content, ECoreType core, int port)
    {
        if (core is not (ECoreType.Xray or ECoreType.sing_box)) throw new NotSupportedException("Custom probes require Xray or sing-box JSON");
        var root = JsonNode.Parse(content) as JsonObject ?? throw new InvalidOperationException("Invalid custom JSON");
        var originalInbound = (root["inbounds"] as JsonArray)?.OfType<JsonObject>().FirstOrDefault();
        var inbound = originalInbound?["tag"]?.ToString() ?? "dicode-custom-probe";
        root.Remove("api");
        root["inbounds"] = new JsonArray(core == ECoreType.Xray
            ? new JsonObject { ["tag"] = inbound, ["listen"] = Global.Loopback, ["port"] = port, ["protocol"] = "socks", ["settings"] = new JsonObject { ["auth"] = "noauth", ["udp"] = false } }
            : new JsonObject { ["tag"] = inbound, ["listen"] = Global.Loopback, ["listen_port"] = port, ["type"] = "socks" });
        if (core == ECoreType.Xray) CustomFakeDnsPolicy.Apply(root);
        return root.ToJsonString();
    }
}
