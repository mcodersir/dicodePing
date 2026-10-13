using System.ComponentModel;

namespace ServiceLib.Services;

/// <summary>Report permanent loader failures once instead of relaunching an unusable binary hundreds of times.</summary>
public static class NativeLaunchPolicy
{
    private static readonly ConcurrentDictionary<string, string> Failures = new();
    private static string Fingerprint(string path)
    {
        var file = new FileInfo(path); return Path.GetFullPath(path) + "|" + file.Length + "|" + file.LastWriteTimeUtc.Ticks;
    }
    public static ushort ReadWindowsMachine(string path)
    {
        using var stream = File.OpenRead(path); using var reader = new BinaryReader(stream);
        if (stream.Length < 64 || reader.ReadUInt16() != 0x5a4d) throw new InvalidDataException("The connection core is not a valid Windows executable. Reinstall the complete Windows package.");
        stream.Position = 0x3c; var offset = reader.ReadInt32();
        if (offset < 64 || offset > stream.Length - 6) throw new InvalidDataException("The connection core executable is incomplete.");
        stream.Position = offset; if (reader.ReadUInt32() != 0x00004550) throw new InvalidDataException("The connection core executable is damaged.");
        var machine = reader.ReadUInt16(); if (machine is not (0x014c or 0x8664 or 0xaa64)) throw new InvalidDataException("Unsupported Windows executable architecture.");
        return machine;
    }
    public static void Validate(string path)
    {
        if (Failures.TryGetValue(Fingerprint(path), out var message)) throw new InvalidOperationException(message);
        if (!OperatingSystem.IsWindows()) return;
        if (!OperatingSystem.IsWindowsVersionAtLeast(10)) throw new PlatformNotSupportedException("DicodePing and its current connection cores require Windows 10 or newer (64-bit). Windows 8.1 cannot run this package.");
        var machine = ReadWindowsMachine(path);
        if ((machine == 0x8664 && RuntimeInformation.OSArchitecture == Architecture.X86) || (machine == 0xaa64 && RuntimeInformation.OSArchitecture != Architecture.Arm64))
            throw new PlatformNotSupportedException("The connection core architecture does not match this Windows installation.");
    }
    public static bool RecordLoaderFailure(string path, Exception error)
    {
        if (error is not Win32Exception { NativeErrorCode: 193 or 216 }) return false;
        var message = "Windows rejected the connection core (invalid or incompatible executable). Use Windows 10+ 64-bit and reinstall the complete package; check whether security software quarantined a file. The repeated start attempts were stopped.";
        Failures[Fingerprint(path)] = message; return true;
    }
}
