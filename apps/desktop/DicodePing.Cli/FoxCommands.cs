using System.Text.Json;
using System.Text.Json.Nodes;
using ServiceLib.Services;

internal static class FoxCommands
{
    public static async Task<int> Execute(string[] args, CancellationToken token)
    {
        var action = args.Length > 1 ? args[1] : "accounts";
        string Id() => args.Length > 2 ? args[2] : throw new ArgumentException("Specify the account ID shown by fox accounts");
        switch (action)
        {
            case "accounts":
                // Public fields only: never serialize a token-bearing FoxAccount.
                Console.WriteLine(JsonSerializer.Serialize((await FoxAccounts.ListAsync()).Select(a => new { id = a.Id, email = a.Email, country = a.Country, verificationRequired = a.Pending, quota = a.Info }), new JsonSerializerOptions { WriteIndented = true }));
                break;
            case "locations":
                Console.WriteLine((await FoxAccounts.RequestAsync(new JsonObject { ["operation"] = "locations" }, token))["locations"]?.ToJsonString()); break;
            case "login":
                Console.Error.Write("Mozilla account email: "); var email = Console.ReadLine() ?? "";
                Console.Error.Write("Password (not saved): "); var password = Secret();
                var signed = await FoxAccounts.LoginAsync(email, password, token); password = "";
                Console.WriteLine($"Account: {signed.Id}; " + (signed.Pending ? "verification required: use fox verify <id>" : "Fox profile added")); break;
            case "verify":
                Console.Error.Write("Verification code: "); var code = Secret();
                await FoxAccounts.VerifyAsync(Id(), code, token); Console.WriteLine("Verified; Fox profile added"); break;
            case "refresh":
                await FoxAccounts.RefreshAsync(Id(), true, token); Console.WriteLine("Account and profile updated"); break;
            case "location":
                if (args.Length < 4 || !(args[3] == "REC" || (args[3].Length == 2 && args[3].All(char.IsAsciiLetter)))) throw new ArgumentException("fox location <id> <REC|country code>");
                var account = await FoxAccounts.GetAsync(Id()); account.Country = args[3].ToUpperInvariant(); await FoxAccounts.SaveAsync(account); await FoxProfiles.SyncAsync(account); Console.WriteLine("Fox location saved"); break;
            case "remove":
                await FoxAccounts.RemoveAsync(Id()); Console.WriteLine("Local account and its Fox subscription removed"); break;
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
