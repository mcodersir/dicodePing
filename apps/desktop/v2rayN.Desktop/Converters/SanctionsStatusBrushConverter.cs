using Avalonia.Data.Converters;

namespace v2rayN.Desktop.Converters;

public sealed class SanctionsStatusBrushConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        new SolidColorBrush(IsAccessible(value?.ToString())
            ? Color.Parse("#22C55E")
            : Color.Parse("#EF4444"));

    private static bool IsAccessible(string? value) =>
        value?.StartsWith("قابل دسترسی", StringComparison.Ordinal) == true
        || value?.StartsWith("Accessible", StringComparison.OrdinalIgnoreCase) == true;

    public object? ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) => null;
}
