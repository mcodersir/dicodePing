namespace ServiceLib.Services;

public static class NativeProfileTemplates
{
    public static string Build(string kind, string server, int port, string username, string password, string extra = "")
    {
        if (string.IsNullOrWhiteSpace(server) || port is < 1 or > 65535) throw new ArgumentException("Server and valid port are required");
        if (kind is not ("ssh" or "socks") && string.IsNullOrWhiteSpace(password)) throw new ArgumentException("Password is required");
        var proxy = new JsonObject { ["type"] = kind, ["tag"] = "proxy", ["server"] = server.Trim(), ["server_port"] = port };
        switch (kind)
        {
            case "socks":
                proxy["version"] = "5";
                if (username.IsNotEmpty()) { proxy["username"] = username; proxy["password"] = password; }
                break;
            case "snell": proxy["version"] = 4; proxy["psk"] = password; break;
            case "anytls": proxy["password"] = password; proxy["tls"] = new JsonObject { ["enabled"] = true, ["server_name"] = extra.IsNotEmpty() ? extra : server.Trim() }; break;
            case "ssh":
                if (username.IsNullOrEmpty()) throw new ArgumentException("SSH username is required");
                proxy["user"] = username; proxy["password"] = password;
                if (extra.IsNotEmpty()) proxy["host_key"] = new JsonArray(extra);
                break;
            case "openconnect":
                proxy.Remove("server_port"); proxy["system"] = false; proxy["flavor"] = "anyconnect";
                proxy["server"] = new UriBuilder("https", server.Trim(), port).Uri.AbsoluteUri;
                proxy["username"] = username; proxy["password"] = password;
                if (extra.IsNotEmpty()) proxy["tls"] = new JsonObject { ["certificate_authority"] = new JsonArray(extra) };
                break;
            case "openvpn-client":
                proxy["system"] = false; proxy["network"] = "udp"; proxy["mode"] = "tls";
                proxy["username"] = username; proxy["password"] = password;
                proxy["tls"] = new JsonObject { ["server_name"] = server.Trim(), ["certificate"] = new JsonArray(extra) };
                if (extra.IsNullOrEmpty()) throw new ArgumentException("OpenVPN server CA certificate is required");
                break;
            default: throw new ArgumentException("Unsupported template");
        }
        var root = new JsonObject {
            ["log"] = new JsonObject { ["level"] = "warn" },
            ["inbounds"] = new JsonArray(new JsonObject { ["type"] = "mixed", ["tag"] = "socks", ["listen"] = Global.Loopback, ["listen_port"] = Utils.GetFreePort(AppManager.Instance.GetLocalPort(EInboundProtocol.mixed) + 100) }),
            ["route"] = new JsonObject { ["final"] = "proxy", ["auto_detect_interface"] = true },
        };
        root[kind is "openconnect" or "openvpn-client" ? "endpoints" : "outbounds"] = new JsonArray(proxy);
        return root.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
    }
}
