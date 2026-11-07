using System.IO.Compression;
using AmazTool;
using Xunit;

public class UpdateArchiveTests
{
    [Theory]
    [InlineData("")]
    [InlineData("DicodePing/")]
    public void KeepsRootFilesAndUpdatesBundledCores(string prefix)
    {
        using var bytes = new MemoryStream();
        using var zip = new ZipArchive(bytes, ZipArchiveMode.Create, true);
        foreach (var name in new[] { "DicodePing.exe", "bin/xray/xray.exe", "guiConfigs/account.json" })
            using (var writer = new StreamWriter(zip.CreateEntry(prefix + name).Open())) writer.Write("payload");
        zip.Dispose(); bytes.Position = 0;
        using var read = new ZipArchive(bytes, ZipArchiveMode.Read);
        var plan = UpdateArchive.Plan(read, Path.GetTempPath());
        Assert.Equal(2, plan.Count);
        Assert.Contains(plan, item => item.Target.EndsWith(Path.Combine("bin", "xray", "xray.exe")));
    }
    [Theory]
    [InlineData("../stolen.exe")]
    [InlineData("bin/../../stolen.exe")]
    [InlineData("C:/stolen.exe")]
    [InlineData("bin\\stolen.exe")]
    public void RejectsUnsafePathsBeforeReplacingAnything(string path)
    {
        using var bytes = new MemoryStream();
        using var zip = new ZipArchive(bytes, ZipArchiveMode.Create, true);
        foreach (var name in new[] { "DicodePing.exe", path })
            using (var writer = new StreamWriter(zip.CreateEntry(name).Open())) writer.Write("payload");
        zip.Dispose(); bytes.Position = 0;
        using var read = new ZipArchive(bytes, ZipArchiveMode.Read);
        Assert.Throws<InvalidDataException>(() => UpdateArchive.Plan(read, Path.GetTempPath()));
    }
}
