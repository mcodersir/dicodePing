using NativeWebView.Core;

namespace NativeWebView.Platform.Linux;

public static class NativeWebViewPlatformLinuxExtensions
{
    public static NativeWebViewBackendFactory UseNativeWebViewLinux(this NativeWebViewBackendFactory factory)
    {
        ArgumentNullException.ThrowIfNull(factory);
        NativeWebViewPlatformLinuxModule.Register(factory);
        return factory;
    }
}
