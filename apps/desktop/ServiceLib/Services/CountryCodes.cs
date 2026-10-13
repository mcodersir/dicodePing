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
        foreach (var code in "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CP CR CU CV CW CX CY CZ DE DG DJ DK DM DO DZ EC EE EG EH ER ES ET EU FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU IC ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PC PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM UN US UY UZ VA VC VE VG VI VN VU WF WS XK YE YT ZA ZM ZW".Split(' ')) names[code] = code;
        names["Congo, Republic of"] = "CG"; names["Congo, Democratic Republic of"] = "CD";
        names["UK"] = "GB"; names["XK"] = "XK"; names["EU"] = "EU";
        return names;
    }
    public static string FromLocation(string? location)
    {
        if (string.IsNullOrWhiteSpace(location)) return "";
        var text = location.Trim();
        var runes = text.EnumerateRunes().ToArray();
        for (var i = 0; i + 1 < runes.Length; i++)
            if (runes[i].Value is >= 0x1F1E6 and <= 0x1F1FF && runes[i+1].Value is >= 0x1F1E6 and <= 0x1F1FF)
                return string.Concat((char)('A'+runes[i].Value-0x1F1E6), (char)('A'+runes[i+1].Value-0x1F1E6));
        foreach (var pair in Names.Where(x => x.Key.Length > 2).OrderByDescending(x => x.Key.Length))
            if (text.Equals(pair.Key, StringComparison.OrdinalIgnoreCase) || text.StartsWith(pair.Key + " ", StringComparison.OrdinalIgnoreCase)
                || text.StartsWith(pair.Key + ",", StringComparison.OrdinalIgnoreCase)) return pair.Value;
        foreach (var word in Regex.Matches(text, @"(?<![A-Za-z])[A-Z]{2}(?![A-Za-z])").Cast<Match>())
            if (Names.TryGetValue(word.Value, out var code)) return code;
        if (text.Length == 2 && Names.TryGetValue(text, out var exact)) return exact;
        return "";
    }
}
