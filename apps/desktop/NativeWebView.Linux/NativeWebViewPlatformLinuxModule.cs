using NativeWebView.Core;

namespace NativeWebView.Platform.Linux;

public static class NativeWebViewPlatformLinuxModule
{
    public static void Register(NativeWebViewBackendFactory factory)
    {
        ArgumentNullException.ThrowIfNull(factory);

        factory.RegisterNativeWebViewBackend(
            NativeWebViewPlatform.Linux,
            static () => new LinuxNativeWebViewBackend(),
            LinuxPlatformFeatures.Instance);

        factory.RegisterPlatformDiagnostics(
            NativeWebViewPlatform.Linux,
            static () => LinuxPlatformDiagnostics.Create());

        factory.RegisterNativeWebDialogBackend(
            NativeWebViewPlatform.Linux,
            static () => new LinuxNativeWebDialogBackend());

        factory.RegisterWebAuthenticationBrokerBackend(
            NativeWebViewPlatform.Linux,
            static () => new LinuxWebAuthenticationBrokerBackend());
    }

    public static void RegisterDefault()
    {
        Register(NativeWebViewRuntime.Factory);
    }
}
