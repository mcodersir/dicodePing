using System.Globalization;
namespace ServiceLib.Services;
public static class FoxDates
{
    public static string Format(DateTimeOffset date)
    {
        var p = new PersianCalendar(); var d = date.LocalDateTime;
        return $"{p.GetYear(d):0000}/{p.GetMonth(d):00}/{p.GetDayOfMonth(d):00} · {d:yyyy-MM-dd}";
    }
}
public static class FoxLocationCache
{
    private static string PathName => Utils.GetConfigPath("fox-countries.json");
    public static string[] Read() { try { return (System.Text.Json.JsonSerializer.Deserialize<string[]>(File.ReadAllText(PathName)) ?? []).Where(v => v == "REC" || v.Length == 2 && v.All(char.IsAsciiLetter)).Distinct().ToArray(); } catch { return System.Text.Json.JsonSerializer.Deserialize<string[]>(EmbedUtils.GetEmbedText("ServiceLib.Sample.fox-countries.json")) ?? ["REC"]; } }
    public static void Write(string[] values) { Directory.CreateDirectory(Path.GetDirectoryName(PathName)!); File.WriteAllText(PathName, System.Text.Json.JsonSerializer.Serialize(values)); }
}
