using System.Text.Json.Nodes;

namespace ServiceLib.Services;

public static class FoxRuntimeBridge
{
    public static void RebindFile(string path, int previousPort, int port)
    {
        var root = JsonNode.Parse(File.ReadAllText(path)) ?? throw new InvalidDataException("Empty proxy configuration");
        var changed = 0;
        void Visit(JsonNode? node)
        {
            if (node is JsonObject obj)
            {
                var host = obj["address"]?.ToString() ?? obj["server"]?.ToString();
                var key = obj.ContainsKey("server_port") ? "server_port" : "port";
                if (host == "127.0.0.1" && obj[key]?.ToString() == previousPort.ToString()) { obj[key] = port; changed++; }
                foreach (var child in obj.ToList()) Visit(child.Value);
            }
            else if (node is JsonArray array) foreach (var child in array) Visit(child);
        }
        Visit(root["outbounds"]);
        if (changed == 0) throw new InvalidDataException("The generated configuration does not contain the Fox bridge");
        File.WriteAllText(path, root.ToJsonString());
    }
}
