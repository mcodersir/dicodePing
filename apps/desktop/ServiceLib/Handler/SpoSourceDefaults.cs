namespace ServiceLib.Handler;

/// <summary>
///     Built-in DicodeSpo source list. Order IS priority: the aggregator walks
///     this list top-down and stops when the configured cap is reached, so the
///     light, curated sources come first and the heavy dumps sit at the end.
/// </summary>
public static class SpoSourceDefaults
{
    public static List<SpoSourceItem> Sources =>
    [
        new() { Name = "Patterniha Free-Configs", Url = "https://raw.githubusercontent.com/patterniha/Free-Configs/main/configs.txt" },
        new() { Name = "0xRadikal Top100", Url = "https://raw.githubusercontent.com/0xRadikal/Free-v2ray-Configs/refs/heads/main/top100.txt" },
        new() { Name = "roosterkid openproxylist", Url = "https://raw.githubusercontent.com/roosterkid/openproxylist/main/V2RAY_RAW.txt" },
        new() { Name = "ermaozi get_subscribe", Url = "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt" },
        new() { Name = "MatinGhanbari v2ray-configs", Url = "https://raw.githubusercontent.com/MatinGhanbari/v2ray-configs/main/subscriptions/v2ray/all_sub.txt" },
        new() { Name = "barry-far v2ray-config", Url = "https://raw.githubusercontent.com/barry-far/v2ray-config/main/All_Configs_Sub.txt" },
        new() { Name = "SoliSpirit v2ray-configs", Url = "https://raw.githubusercontent.com/SoliSpirit/v2ray-configs/main/all_configs.txt" },
        new() { Name = "Pawdroid Free-servers", Url = "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub" },
        new() { Name = "peasoft NoMoreWalls", Url = "https://raw.githubusercontent.com/peasoft/NoMoreWalls/master/list.txt" },
        new() { Name = "Epodonios v2ray-configs", Url = "https://raw.githubusercontent.com/Epodonios/v2ray-configs/main/All_Configs_Sub.txt" },
    ];
}
