using System.Text.Json;
using System.Text.Json.Nodes;
using ServiceLib.Services;

internal static class FoxCommands
{
    public static async Task<int> Execute(string[] args, CancellationToken token)
    {
        var action = args.Length > 1 ? args[1] : "accounts";
        string Id() => args.Length > 2 ? args[2] : throw new ArgumentException(CliText.T("شناسه نمایش‌داده‌شده در fox accounts را وارد کنید", "Specify the account ID shown by fox accounts"));
        switch (action)
        {
            case "accounts":
                // Public fields only: never serialize a token-bearing FoxAccount.
                Console.WriteLine(JsonSerializer.Serialize((await FoxAccounts.ListAsync()).Select(a => new { id = a.Id, email = a.Email, country = a.Country, verificationRequired = a.Pending, quota = a.Info, usedBytes = a.Info["quota_max"] is not null && a.Info["quota_remaining"] is not null ? Math.Max(0, a.Info["quota_max"]!.GetValue<long>() - a.Info["quota_remaining"]!.GetValue<long>()) : (long?)null }), new JsonSerializerOptions { WriteIndented = true }));
                break;
            case "locations":
                Console.WriteLine((await FoxAccounts.RequestAsync(new JsonObject { ["operation"] = "locations" }, token))["locations"]?.ToJsonString()); break;
            case "login":
                Console.Error.Write(CliText.T("۱ · ایمیل حساب موزیلا: ", "1 · Mozilla account email: ")); var email = Console.ReadLine() ?? "";
                Console.Error.Write(CliText.T("رمز عبور (ذخیره نمی‌شود): ", "Password (not saved): ")); var password = Secret();
                var signed = await FoxAccounts.LoginAsync(email, password, token); password = "";
                if (signed.Pending) {
                    Console.Error.Write(CliText.T("۲ · کد تأیید: ", "2 · Verification code: "));
                    signed = await FoxAccounts.VerifyAsync(signed.Id, Secret(), token);
                }
                Console.Error.Write(CliText.T("۳ · کد کشور (Enter برای REC): ", "3 · Country code (Enter for REC): "));
                var country = (Console.ReadLine() ?? "").Trim().ToUpperInvariant();
                if (country.Length > 0 && !(country == "REC" || (country.Length == 2 && country.All(char.IsAsciiLetter)))) throw new ArgumentException(CliText.T("کد کشور نامعتبر است", "Invalid country code"));
                signed.Country = country.Length == 0 ? "REC" : country;
                await FoxAccounts.SaveAsync(signed); await FoxProfiles.SyncAsync(signed);
                Console.WriteLine(CliText.T($"حساب {signed.Id} آماده است؛ سرور را از profiles انتخاب کنید و connect <id> را اجرا کنید.", $"Account {signed.Id} ready; choose its profile from profiles and run connect <id>.")); break;
            case "verify":
                Console.Error.Write(CliText.T("کد تأیید: ", "Verification code: ")); var code = Secret();
                await FoxAccounts.VerifyAsync(Id(), code, token); Console.WriteLine(CliText.T("حساب تأیید و سرور روباه اضافه شد", "Verified; Fox profile added")); break;
            case "refresh":
                await FoxAccounts.RefreshAsync(Id(), true, token); Console.WriteLine(CliText.T("حساب و سرور تازه شدند", "Account and profile updated")); break;
            case "location":
                if (args.Length < 4 || !(args[3] == "REC" || (args[3].Length == 2 && args[3].All(char.IsAsciiLetter)))) throw new ArgumentException("fox location <id> <REC|country code>");
                var account = await FoxAccounts.GetAsync(Id()); account.Country = args[3].ToUpperInvariant(); await FoxAccounts.SaveAsync(account); await FoxProfiles.SyncAsync(account); Console.WriteLine(CliText.T("کشور روباه ذخیره شد", "Fox location saved")); break;
            case "remove":
                await FoxAccounts.RemoveAsync(Id()); Console.WriteLine(CliText.T("حساب و ساب روباه از برنامه حذف شدند", "Local account and its Fox subscription removed")); break;
            default: throw new ArgumentException("fox accounts|locations|login|verify <id>|refresh <id>|location <id> <code>|remove <id>");
        }
        return 0;
    }
    private static string Secret()
    {
        if (Console.IsInputRedirected) return Console.ReadLine() ?? "";
        var buffer = new System.Text.StringBuilder();
        while (true)
        {
            var key = Console.ReadKey(intercept: true);
            if (key.Key == ConsoleKey.Enter) { Console.Error.WriteLine(); return buffer.ToString(); }
            if (key.Key == ConsoleKey.Backspace) { if (buffer.Length > 0) buffer.Length--; }
            else if (!char.IsControl(key.KeyChar)) buffer.Append(key.KeyChar);
        }
    }
}
