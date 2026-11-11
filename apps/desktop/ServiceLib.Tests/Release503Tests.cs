using ServiceLib.Services;
using Xunit;

namespace ServiceLib.Tests;
public class Release503Tests
{
    [Fact]
    public void UdpOnlyPortOwnerCannotBeSelectedAsTheMixedProxyPort()
    {
        using var occupied = new UdpClient(new IPEndPoint(IPAddress.Any, 0));
        var port = ((IPEndPoint)occupied.Client.LocalEndPoint!).Port;
        var candidate = Utils.GetFreePort(port);
        Assert.NotEqual(port, candidate);
        Assert.InRange(candidate, 1, 65535);
    }

    [Theory]
    [InlineData("FwpmTransactionCommit0 failed > The object is referenced by other objects so cannot be deleted.", true)]
    [InlineData("FwpmTransactionCommit0 failed > 0x8032000a", true)]
    [InlineData("FwpmTransactionCommit0 failed > Access denied", false)]
    [InlineData("listen tcp: address already in use", false)]
    public void OnlyTheReportedWfpConflictTriggersBoundedRecovery(string message, bool expected) =>
        Assert.Equal(expected, WindowsTunRuntime.IsWfpObjectInUseFailure(message));
}
