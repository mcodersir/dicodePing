from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "third_party" / "network-engine" / "runtime" / "ServiceLib"

CHECKS: dict[str, tuple[str, ...]] = {
    "Handler/ConfigHandler.cs": (
        "public static async Task<int> AddBatchServers(Config config, string strData, string subid, bool isSub)",
        "public static async Task<int> SetDefaultServerIndex(Config config, string? indexId)",
        "public static async Task<int> SaveConfig(Config config)",
    ),
    "Handler/Builder/CoreConfigContextBuilder.cs": (
        "public static async Task<CoreConfigContextBuilderAllResult> BuildAll(Config config, ProfileItem node)",
        "public bool Success => MainResult.Success",
        "public NodeValidatorResult CombinedValidatorResult",
    ),
    "Handler/SysProxy/SysProxyHandler.cs": (
        "public static async Task<bool> UpdateSysProxy(Config config, bool forceDisable)",
    ),
    "Handler/Fmt/FmtHandler.cs": (
        "public static string? GetShareUri(ProfileItem item)",
    ),
    "Manager/AppManager.cs": (
        "public ECoreType RunningCoreType { get; set; }",
        "public int GetLocalPort(EInboundProtocol protocol)",
        "public async Task<List<ProfileItem>?> ProfileItems(string subid)",
        "public async Task<ProfileItem?> GetProfileItem(string indexId)",
        "public async Task<List<ProfileItem>> GetProfileItemsByIndexIds(IEnumerable<string> indexIds)",
    ),
    "Manager/CoreManager.cs": (
        "public async Task Init(Config config, Func<bool, string, Task> updateFunc)",
        "public async Task LoadCore(CoreConfigContext? mainContext, CoreConfigContext? preContext)",
        "public async Task CoreStop()",
    ),
    "Manager/ProfileExManager.cs": (
        "public async Task Init()",
    ),
    "Manager/StatisticsManager.cs": (
        "public async Task Init(Config config, Func<ServerSpeedItem, Task> updateFunc)",
    ),
    "Models/Configs/ConfigItems.cs": (
        "public bool AutoRoute { get; set; } = true;",
        "public bool StrictRoute { get; set; } = true;",
        "public int Mtu { get; set; }",
        "public string DomainStrategy { get; set; }",
        "public string DomainStrategy4Singbox { get; set; }",
    ),
    "Services/SpeedtestService.cs": (
        "public class SpeedtestService",
        "public void RunLoop(ESpeedActionType actionType, List<ProfileItem> selecteds)",
        "public void ExitLoop()",
    ),
}

errors: list[str] = []
for relative, markers in CHECKS.items():
    path = SERVICE / relative
    if not path.is_file():
        errors.append(f"missing ServiceLib source: {relative}")
        continue
    text = path.read_text(encoding="utf-8", errors="replace")
    for marker in markers:
        if marker not in text:
            errors.append(f"{relative}: API marker not found: {marker}")

program = (ROOT / "corehost" / "Program.cs").read_text(encoding="utf-8", errors="replace")
required_calls = (
    "ConfigHandler.AddBatchServers",
    "ConfigHandler.SetDefaultServerIndex",
    "CoreConfigContextBuilder.BuildAll",
    "CoreManager.Instance.LoadCore",
    "CoreManager.Instance.CoreStop",
    "SysProxyHandler.UpdateSysProxy",
    "SpeedtestService",
    "StatisticsManager.Instance.Init",
    "FmtHandler.GetShareUri",
)
for marker in required_calls:
    if marker not in program:
        errors.append(f"CoreHost no longer references expected ServiceLib API: {marker}")

if errors:
    print("CoreHost/ServiceLib API surface validation failed:")
    for error in errors:
        print(f"- {error}")
    raise SystemExit(1)

print("CoreHost/ServiceLib API surface validation passed")
