using Avalonia.Data.Converters;

namespace v2rayN.Desktop.Converters;

public sealed class SanctionsStatusBrushConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture) =>
        new SolidColorBrush(value?.ToString()?.StartsWith("قابل دسترسی", StringComparison.Ordinal) == true
            ? Color.Parse("#22C55E")
            : Color.Parse("#EF4444"));

    public object? ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture) => null;
}
