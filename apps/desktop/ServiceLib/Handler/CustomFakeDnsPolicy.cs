namespace ServiceLib.Handler;

public static class CustomFakeDnsPolicy
{
    public static void Apply(JsonObject root)
    {
        var servers = root["dns"]?["servers"] as JsonArray;
        if (servers?.Any(server => (server is JsonObject obj ? obj["address"]?.ToString() : server?.ToString()) == "fakedns") != true) return;
        foreach (var inbound in (root["inbounds"] as JsonArray ?? []).OfType<JsonObject>())
        {
            if (inbound["protocol"]?.ToString() is not ("tun" or "socks" or "mixed" or "http")) continue;
            var sniff = inbound["sniffing"] as JsonObject ?? new JsonObject();
            sniff["enabled"] = true;
            sniff["routeOnly"] = false;
            var overrides = sniff["destOverride"] as JsonArray ?? new JsonArray();
            foreach (var protocol in new[] { "fakedns", "http", "tls" })
                if (!overrides.Any(x => x?.ToString() == protocol)) overrides.Add(protocol);
            sniff["destOverride"] = overrides;
            inbound["sniffing"] = sniff;
        }
    }
}
