namespace ServiceLib.Services;

/// <summary>Restore FakeDNS destinations even when optional SNI routing is enabled.</summary>
public static class FakeDnsPolicy
{
    public static void Apply(JsonObject root)
    {
        var servers = root["dns"]?["servers"] as JsonArray;
        var fake = servers?.Any(x => x is JsonValue value ? value.ToString() == "fakedns" : x?["address"]?.ToString() == "fakedns") == true;
        if (!fake) return;
        foreach (var inbound in (root["inbounds"] as JsonArray ?? []).OfType<JsonObject>())
        {
            if (inbound["protocol"]?.ToString() is not ("mixed" or "socks" or "http" or "tun")) continue;
            var sniffing = inbound["sniffing"] as JsonObject ?? new JsonObject();
            var overrides = sniffing["destOverride"] as JsonArray ?? new JsonArray();
            if (!overrides.Any(x => x?.ToString() == "fakedns")) overrides.Add("fakedns");
            sniffing["enabled"] = true; sniffing["routeOnly"] = false;
            sniffing["destOverride"] = overrides; inbound["sniffing"] = sniffing;
        }
    }
}
