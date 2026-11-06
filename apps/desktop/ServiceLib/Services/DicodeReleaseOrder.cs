using System.Text.RegularExpressions;
namespace ServiceLib.Services;
public static class DicodeReleaseOrder
{
    static SemanticVersion Normalize(string value) => new(Regex.Replace(value, @"^(v?4\.9\.)(9[0-9])(?=$|[-+])", m => m.Groups[1].Value + (int.Parse(m.Groups[2].Value) * 10)));
    public static int Compare(string first, string second) => Normalize(first).CompareTo(Normalize(second));
}
