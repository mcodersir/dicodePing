namespace ServiceLib.Handler;

/// <summary>
///     Built-in services for the sanctions reachability probe. These cover the
///     surfaces that actively restrict sanctioned regions: Google AI products,
///     OpenAI, mainstream media platforms and common developer infrastructure.
///     Strict services gate the accessible verdict because they are the most
///     reliable sanctions indicators.
/// </summary>
public static class SanctionsDefaults
{
    public static List<SanctionServiceItem> Services =>
    [
        new() { Name = "Gemini", Url = "https://gemini.google.com/", Strict = true },
        new() { Name = "Google AI Studio", Url = "https://aistudio.google.com/", Strict = true },
        new() { Name = "ChatGPT", Url = "https://chatgpt.com/", Strict = true },
        new() { Name = "OpenAI API", Url = "https://api.openai.com/", Strict = true },
        new() { Name = "YouTube", Url = "https://www.youtube.com/" },
        new() { Name = "YouTube Studio", Url = "https://studio.youtube.com/" },
        new() { Name = "Netflix", Url = "https://www.netflix.com/" },
        new() { Name = "Spotify", Url = "https://open.spotify.com/" },
        new() { Name = "Telegram Web", Url = "https://web.telegram.org/k/" },
        new() { Name = "GitHub", Url = "https://github.com/" },
        new() { Name = "Docker Hub", Url = "https://hub.docker.com/", Strict = true },
        new() { Name = "Hugging Face", Url = "https://huggingface.co/" },
        new() { Name = "Steam", Url = "https://store.steampowered.com/" },
        new() { Name = "Figma", Url = "https://www.figma.com/" },
        new() { Name = "Notion", Url = "https://www.notion.so/" },
        new() { Name = "Canva", Url = "https://www.canva.com/" },
        new() { Name = "Medium", Url = "https://medium.com/" },
        new() { Name = "Wikipedia", Url = "https://www.wikipedia.org/" },
        new() { Name = "JetBrains", Url = "https://www.jetbrains.com/" },
        new() { Name = "Kotlin", Url = "https://kotlinlang.org/" },
        new() { Name = "Android Developers", Url = "https://developer.android.com/" },
        new() { Name = "Google Play", Url = "https://play.google.com/" },
    ];
}
