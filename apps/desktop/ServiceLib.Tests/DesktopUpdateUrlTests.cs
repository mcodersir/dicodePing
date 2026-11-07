using Xunit;

namespace ServiceLib.Tests;
public class DesktopUpdateUrlTests
{
    [Theory]
    [InlineData("5.0.0")]
    [InlineData("4.9.991")]
    public void DownloadTagHasVButPortableFilenameDoesNot(string version)
    {
        var core = CoreInfoManager.Instance.GetCoreInfo(ECoreType.v2rayN)!;
        var url = string.Format(core.DownloadUrlWin64!, version);
        Assert.Equal($"https://github.com/mcodersir/dicodePing/releases/download/v{version}/DicodePing-{version}-windows-x64-portable.zip", url);
    }
}
