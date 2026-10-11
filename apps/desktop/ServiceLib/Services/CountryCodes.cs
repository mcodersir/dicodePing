using System.Globalization;
using System.Text.RegularExpressions;

namespace ServiceLib.Services;

public static class CountryCodes
{
    private static readonly Dictionary<string, string> Names = BuildNames();
    private static Dictionary<string, string> BuildNames()
    {
        var names = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var culture in CultureInfo.GetCultures(CultureTypes.SpecificCultures))
        {
            try
            {
                var region = new RegionInfo(culture.Name);
                names[region.TwoLetterISORegionName] = region.TwoLetterISORegionName;
                names[region.EnglishName] = region.TwoLetterISORegionName;
                names[region.NativeName] = region.TwoLetterISORegionName;
            }
            catch (ArgumentException) { }
        }
        names["UK"] = "GB"; names["XK"] = "XK"; names["EU"] = "EU";
        return names;
    }
    public static string FromLocation(string? location)
    {
        if (string.IsNullOrWhiteSpace(location)) return "";
        var text = location.Trim();
        foreach (var word in Regex.Matches(text, @"(?<![A-Za-z])[A-Za-z]{2}(?![A-Za-z])").Cast<Match>())
            if (Names.TryGetValue(word.Value, out var code)) return code;
        var runes = text.EnumerateRunes().ToArray();
        for (var i = 0; i + 1 < runes.Length; i++)
            if (runes[i].Value is >= 0x1F1E6 and <= 0x1F1FF && runes[i+1].Value is >= 0x1F1E6 and <= 0x1F1FF)
                return string.Concat((char)('A'+runes[i].Value-0x1F1E6), (char)('A'+runes[i+1].Value-0x1F1E6));
        foreach (var pair in Names.Where(x => x.Key.Length > 2).OrderByDescending(x => x.Key.Length))
            if (text.Equals(pair.Key, StringComparison.OrdinalIgnoreCase) || text.StartsWith(pair.Key + " ", StringComparison.OrdinalIgnoreCase)
                || text.StartsWith(pair.Key + ",", StringComparison.OrdinalIgnoreCase)) return pair.Value;
        return "";
    }
}
