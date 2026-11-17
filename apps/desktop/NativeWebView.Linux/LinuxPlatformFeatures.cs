using NativeWebView.Core;

namespace NativeWebView.Platform.Linux;

internal static class LinuxPlatformFeatures
{
    public static readonly IWebViewPlatformFeatures Instance = new WebViewPlatformFeatures(
        NativeWebViewPlatform.Linux,
        NativeWebViewFeature.EmbeddedView |
        NativeWebViewFeature.Dialog |
        NativeWebViewFeature.AuthenticationBroker |
        NativeWebViewFeature.ContextMenu |
        NativeWebViewFeature.ZoomControl |
        NativeWebViewFeature.Printing |
        NativeWebViewFeature.WebResourceRequestInterception |
        NativeWebViewFeature.NewWindowRequestInterception |
        NativeWebViewFeature.EnvironmentOptions |
        NativeWebViewFeature.ControllerOptions |
        NativeWebViewFeature.NativePlatformHandle |
        NativeWebViewFeature.CookieManager |
        NativeWebViewFeature.CommandManager |
        NativeWebViewFeature.ScriptExecution |
        NativeWebViewFeature.WebMessageChannel |
        NativeWebViewFeature.GpuSurfaceRendering |
        NativeWebViewFeature.OffscreenRendering |
        NativeWebViewFeature.RenderFrameCapture |
        NativeWebViewFeature.ProxyConfiguration |
        NativeWebViewFeature.Favicon |
        NativeWebViewFeature.Downloads |
        NativeWebViewFeature.DocumentStartScriptInjection |
        NativeWebViewFeature.StatusText |
        NativeWebViewFeature.EmbeddedSnapshotCapture |
        NativeWebViewFeature.ZoomFactorChangeNotification);
}
