namespace ServiceLib.Handler;

/// <summary>
/// Core configuration file processing class
/// </summary>
public static class CoreConfigHandler
{
    private static readonly string _tag = "CoreConfigHandler";

    public static async Task<RetResult> GenerateClientConfig(CoreConfigContext context, string? fileName)
    {
        var config = AppManager.Instance.Config;
        var result = new RetResult();
        var node = context.Node;

        if (node.ConfigType == EConfigType.Custom)
        {
            result = node.CoreType switch
            {
                ECoreType.mihomo => await new CoreConfigClashService(config, context.IsTunEnabled).GenerateClientCustomConfig(node, fileName),
                _ => await GenerateClientCustomConfig(config, node, fileName)
            };
        }
        else if (context.RunCoreType == ECoreType.sing_box)
        {
            result = new CoreConfigSingboxService(context).GenerateClientConfigContent();
        }
        else
        {
            result = new CoreConfigV2rayService(context).GenerateClientConfigContent();
        }
        if (result.Success != true)
        {
            return result;
        }
        if (fileName.IsNotEmpty() && result.Data != null)
        {
            await File.WriteAllTextAsync(fileName, result.Data.ToString());
        }

        return result;
    }

    private static async Task<RetResult> GenerateClientCustomConfig(Config config, ProfileItem node, string? fileName)
    {
        var ret = new RetResult();
        try
        {
            if (node == null || fileName is null)
            {
                ret.Msg = ResUI.CheckServerSettings;
                return ret;
            }

            if (File.Exists(fileName))
            {
                File.SetAttributes(fileName, FileAttributes.Normal); //If the file has a read-only attribute, direct deletion will fail
                File.Delete(fileName);
            }

            var addressFileName = node.Address;
            if (!File.Exists(addressFileName))
            {
                addressFileName = Utils.GetConfigPath(addressFileName);
            }
            if (!File.Exists(addressFileName))
            {
                ret.Msg = ResUI.FailedGenDefaultConfiguration;
                return ret;
            }
            File.Copy(addressFileName, fileName);
            File.SetAttributes(fileName, FileAttributes.Normal); //Copy will keep the attributes of addressFileName, so we need to add write permissions to fileName just in case of addressFileName is a read-only file.

            ApplyDomainFilterToCustomConfig(config, fileName);

            //check again
            if (!File.Exists(fileName))
            {
                ret.Msg = ResUI.FailedGenDefaultConfiguration;
                return ret;
            }

            ret.Msg = string.Format(ResUI.SuccessfulConfiguration, "");
            ret.Success = true;
            return await Task.FromResult(ret);
        }
        catch (Exception ex)
        {
            Logging.SaveLog(_tag, ex);
            ret.Msg = ResUI.FailedGenDefaultConfiguration;
            return ret;
        }
    }

    private static void ApplyDomainFilterToCustomConfig(Config config, string fileName)
    {
        var domains = config.RoutingBasicItem.DomainFilterList?
            .Select(x => x.Trim().TrimEnd('.'))
            .Where(x => x.IsNotEmpty())
            .Select(x => x.StartsWith("domain:", StringComparison.OrdinalIgnoreCase)
                || x.StartsWith("full:", StringComparison.OrdinalIgnoreCase)
                || x.StartsWith("regexp:", StringComparison.OrdinalIgnoreCase)
                || x.StartsWith("geosite:", StringComparison.OrdinalIgnoreCase) ? x : $"domain:{x}")
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray() ?? [];
        var mode = config.RoutingBasicItem.DomainFilterMode;
        if (domains.Length == 0 || mode == "off") return;

        if (JsonNode.Parse(File.ReadAllText(fileName)) is not JsonObject root) return;
        var outbounds = root["outbounds"] as JsonArray;
        var proxyTag = outbounds?.OfType<JsonObject>()
            .Select(x => x["tag"]?.GetValue<string>())
            .FirstOrDefault(x => x.IsNotEmpty() && x != Global.DirectTag && x != Global.BlockTag)
            ?? Global.ProxyTag;
        var directTag = outbounds?.OfType<JsonObject>()
            .FirstOrDefault(x => x["protocol"]?.GetValue<string>() == "freedom")?["tag"]?.GetValue<string>();
        if (directTag.IsNullOrEmpty())
        {
            directTag = Global.DirectTag;
            outbounds ??= new JsonArray();
            outbounds.Add(new JsonObject { ["tag"] = directTag, ["protocol"] = "freedom" });
            root["outbounds"] = outbounds;
        }

        var routing = root["routing"] as JsonObject ?? new JsonObject();
        var rules = routing["rules"] as JsonArray ?? new JsonArray();
        var domainArray = new JsonArray();
        foreach (var domain in domains) domainArray.Add(domain);
        rules.Insert(0, new JsonObject
        {
            ["type"] = "field",
            ["domain"] = domainArray,
            ["outboundTag"] = mode == "only" ? proxyTag : directTag,
        });
        if (mode == "only")
        {
            rules.Add(new JsonObject
            {
                ["type"] = "field",
                ["network"] = "tcp,udp",
                ["outboundTag"] = directTag,
            });
        }
        routing["rules"] = rules;
        root["routing"] = routing;
        File.WriteAllText(fileName, root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
    }

    public static async Task<RetResult> GenerateClientSpeedtestConfig(Config config, string fileName, List<ServerTestItem> selecteds, ECoreType coreType)
    {
        var result = new RetResult();
        var dummyNode = new ProfileItem
        {
            CoreType = coreType
        };
        var builderResult = await CoreConfigContextBuilder.Build(config, dummyNode);
        var context = builderResult.Context;
        foreach (var testItem in selecteds)
        {
            var node = testItem.Profile;
            var (actNode, _) = await CoreConfigContextBuilder.ResolveNodeAsync(context, node, true);
            if (node.IndexId == actNode.IndexId)
            {
                continue;
            }
            context.ServerTestItemMap[node.IndexId] = actNode.IndexId;
        }
        if (coreType == ECoreType.sing_box)
        {
            result = new CoreConfigSingboxService(context).GenerateClientSpeedtestConfig(selecteds);
        }
        else if (coreType == ECoreType.Xray)
        {
            result = new CoreConfigV2rayService(context).GenerateClientSpeedtestConfig(selecteds);
        }
        if (result.Success != true)
        {
            return result;
        }
        await File.WriteAllTextAsync(fileName, result.Data.ToString());
        return result;
    }

    public static async Task<RetResult> GenerateClientSpeedtestConfig(Config config, CoreConfigContext context, ServerTestItem testItem, string fileName)
    {
        var result = new RetResult();
        var initPort = AppManager.Instance.GetLocalPort(EInboundProtocol.speedtest);
        var port = Utils.GetFreePort(initPort + testItem.QueueNum);
        testItem.Port = port;

        if (context.RunCoreType == ECoreType.sing_box)
        {
            result = new CoreConfigSingboxService(context).GenerateClientSpeedtestConfig(port);
        }
        else
        {
            result = new CoreConfigV2rayService(context).GenerateClientSpeedtestConfig(port);
        }
        if (result.Success != true)
        {
            return result;
        }

        await File.WriteAllTextAsync(fileName, result.Data.ToString());
        return result;
    }
}
