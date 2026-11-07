using Xunit;
using ServiceLib.Services;
namespace ServiceLib.Tests;
public class DicodeReleaseOrderTests
{
 [Theory]
 [InlineData("4.9.92")][InlineData("4.9.98")][InlineData("4.9.982")][InlineData("4.9.983")][InlineData("4.9.985")]
 public void Release99FollowsHistoricalHotfixes(string old) { Assert.True(DicodeReleaseOrder.Compare("4.9.991",old)>0); Assert.True(DicodeReleaseOrder.Compare(old,"4.9.991")<0); }
 [Fact] public void FutureAndPrereleaseOrderingRemainValid() { Assert.True(DicodeReleaseOrder.Compare("4.10.0","4.9.991")>0);Assert.True(DicodeReleaseOrder.Compare("4.9.991","4.9.991-beta.1")>0); }
}
