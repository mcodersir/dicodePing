using AwesomeAssertions;
using Xunit;

namespace ServiceLib.Tests.CoreConfig;

public class ProxyGroupCycleTests
{
    [Theory]
    [InlineData(ECoreType.Xray)]
    [InlineData(ECoreType.sing_box)]
    public void NestedChainPolicyCycleIsRejectedWithoutRecursing(ECoreType core)
    {
        var config = CoreConfigTestFactory.CreateConfig(core);
        CoreConfigTestFactory.BindAppManagerConfig(config);
        var chain = CoreConfigTestFactory.CreateProxyChainNode(core, "chain", "chain", ["group"]);
        var group = CoreConfigTestFactory.CreatePolicyGroupNode(core, "group", "group", ["chain"]);
        var context = CoreConfigTestFactory.CreateContext(config, chain, core);
        context.AllProxiesMap[chain.IndexId] = chain;
        context.AllProxiesMap[group.IndexId] = group;
        var result = core == ECoreType.Xray
            ? new CoreConfigV2rayService(context).GenerateClientConfigContent()
            : new CoreConfigSingboxService(context).GenerateClientConfigContent();
        result.Success.Should().BeFalse();
    }
}
