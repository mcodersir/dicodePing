using NativeWebView.Core;

namespace NativeWebView.Platform.Linux;

internal static class LinuxPlatformDiagnostics
{
    public static NativeWebViewPlatformDiagnostics Create()
    {
        var issues = new List<NativeWebViewDiagnosticIssue>();
        AddContractOnlyControlWarning(issues);

        if (!NativeWebViewDiagnosticsHostPlatformOverride.IsEffectiveHostPlatform(NativeWebViewPlatform.Linux))
        {
            issues.Add(new NativeWebViewDiagnosticIssue(
                code: "linux.host.mismatch",
                severity: NativeWebViewDiagnosticSeverity.Warning,
                message: "Linux backend diagnostics are running on a non-Linux host.",
                recommendation: "Run this diagnostic on Linux to verify WebKitGTK runtime prerequisites."));
        }
        else
        {
            ValidateWebKitGtkVersion(issues);

            var hasDisplay = !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("DISPLAY")) ||
                !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("WAYLAND_DISPLAY"));
            if (!hasDisplay)
            {
                issues.Add(new NativeWebViewDiagnosticIssue(
                    code: "linux.display.missing",
                    severity: NativeWebViewDiagnosticSeverity.Warning,
                    message: "DISPLAY/WAYLAND_DISPLAY is not set.",
                    recommendation: "Set a graphical session variable when running non-headless UI flows."));
            }
        }

        if (issues.Count == 0)
        {
            issues.Add(new NativeWebViewDiagnosticIssue(
                code: "linux.ready",
                severity: NativeWebViewDiagnosticSeverity.Info,
                message: "Linux prerequisite checks passed."));
        }

        return new NativeWebViewPlatformDiagnostics(
            NativeWebViewPlatform.Linux,
            providerName: nameof(LinuxPlatformDiagnostics),
            issues);
    }

    private static void ValidateWebKitGtkVersion(List<NativeWebViewDiagnosticIssue> issues)
    {
        var versionOverride = Environment.GetEnvironmentVariable("NATIVEWEBVIEW_WEBKITGTK_VERSION");
        if (string.IsNullOrWhiteSpace(versionOverride))
        {
            issues.Add(new NativeWebViewDiagnosticIssue(
                code: "linux.webkitgtk.version.unset",
                severity: NativeWebViewDiagnosticSeverity.Warning,
                message: "NATIVEWEBVIEW_WEBKITGTK_VERSION is not set.",
                recommendation: "Set this environment variable in CI or startup diagnostics (expected >= 4.1)."));
            return;
        }

        if (!Version.TryParse(versionOverride, out var parsed))
        {
            issues.Add(new NativeWebViewDiagnosticIssue(
                code: "linux.webkitgtk.version.invalid",
                severity: NativeWebViewDiagnosticSeverity.Warning,
                message: $"Unable to parse NATIVEWEBVIEW_WEBKITGTK_VERSION: {versionOverride}",
                recommendation: "Use version format like 4.1 or 4.1.3."));
            return;
        }

        var minimum = new Version(4, 1);
        if (parsed < minimum)
        {
            issues.Add(new NativeWebViewDiagnosticIssue(
                code: "linux.webkitgtk.version.too_low",
                severity: NativeWebViewDiagnosticSeverity.Error,
                message: $"WebKitGTK {versionOverride} is below required version {minimum}.",
                recommendation: "Upgrade WebKitGTK runtime/dev packages to 4.1+."));
        }
    }

    private static void AddContractOnlyControlWarning(List<NativeWebViewDiagnosticIssue> issues)
    {
        var implementationStatus = NativeWebViewPlatformImplementationStatusMatrix.Get(NativeWebViewPlatform.Linux);
        if (implementationStatus.EmbeddedControl != NativeWebViewRepositoryImplementationStatus.RuntimeImplemented)
        {
            issues.Add(new NativeWebViewDiagnosticIssue(
                code: "linux.control.contract_only",
                severity: NativeWebViewDiagnosticSeverity.Warning,
                message: "Linux currently registers the NativeWebView control contract, but the embedded control runtime is not implemented in this repo yet.",
                recommendation: "Treat Linux embedded control support as planned work and check NativeWebViewPlatformImplementationStatusMatrix before shipping."));
        }
    }
}
