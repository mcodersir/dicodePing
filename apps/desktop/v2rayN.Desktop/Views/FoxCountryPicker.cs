using Avalonia.Controls.Primitives;
using Avalonia.Controls.Templates;
using Avalonia.Input;
using Avalonia.Layout;

namespace v2rayN.Desktop.Views;

public sealed class FoxCountryPicker : UserControl
{
    private readonly Button _button = new() { HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch };
    private readonly TextBox _search = new() { PlaceholderText = FoxUi.T("جستجوی کشور یا کد", "Search country or code"), BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(10), MinHeight = 48 };
    private readonly StackPanel _rows = new() { Spacing = 5 };
    private readonly Popup _popup;
    private string[] _items = [];
    private object? _selected;
    public event EventHandler? SelectionChanged;
    public bool IsDropDownOpen { get => _popup.IsOpen; set { _popup.Width = Math.Max(260, Bounds.Width); _popup.IsOpen = value; } }
    public string SearchText { get => _search.Text ?? ""; set => _search.Text = value; }
    public int VisibleCountryCount => _rows.Children.Count;
    public IDataTemplate? ItemTemplate { get; set; }
    public IEnumerable<string> ItemsSource { get => _items; set { _items = value.Where(v => v == "REC" || v.Length == 2).Select(v => v.ToUpperInvariant()).Distinct().ToArray(); Filter(); } }
    public int SelectedIndex { set => SelectedItem = _items.ElementAtOrDefault(value); }
    public object? SelectedItem {
        get => _selected;
        set {
            if (Equals(value, _selected)) return;
            _selected = value;
            _button.Content = CountryRow(value?.ToString(), false);
            Filter(); SelectionChanged?.Invoke(this, EventArgs.Empty);
        }
    }
    private Control CountryRow(string? code, bool radio)
    {
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("32,*,24"), ColumnSpacing = 10 };
        grid.Children.Add(new CountryFlagIcon { SourceText = code, Width = 28, Height = 19, VerticalAlignment = VerticalAlignment.Center });
        var text = new TextBlock { Text = FoxUi.CountryLabel(code), TextWrapping = TextWrapping.Wrap, VerticalAlignment = VerticalAlignment.Center }; Grid.SetColumn(text, 1); grid.Children.Add(text);
        var indicator = new Border { Width = 18, Height = 18, CornerRadius = new CornerRadius(9), BorderThickness = new Thickness(1.5), VerticalAlignment = VerticalAlignment.Center };
        indicator.Bind(Border.BorderBrushProperty, this.GetObservable(ForegroundProperty));
        if (radio && Equals(code, _selected)) indicator.Child = new Border { Margin = new Thickness(3), CornerRadius = new CornerRadius(5), Background = Foreground };
        if (radio) { Grid.SetColumn(indicator, 2); grid.Children.Add(indicator); }
        return grid;
    }
    public FoxCountryPicker()
    {
        var border = new Border { Padding = new Thickness(12), CornerRadius = new CornerRadius(14), BorderThickness = new Thickness(1), Child = new StackPanel { Spacing = 10, Children = { _search, new ScrollViewer { MaxHeight = 300, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled, Content = _rows } } } };
        border.Bind(Border.BackgroundProperty, new Avalonia.Markup.Xaml.MarkupExtensions.DynamicResourceExtension("DicodeSurfaceElevated"));
        border.Bind(Border.BorderBrushProperty, new Avalonia.Markup.Xaml.MarkupExtensions.DynamicResourceExtension("DicodeBorder"));
        _popup = new Popup { PlacementTarget = _button, IsLightDismissEnabled = true, Placement = PlacementMode.Bottom, Child = border };
        Content = new Panel { Children = { _button, _popup } };
        _button.Click += (_, _) => { _search.Text = ""; Filter(); IsDropDownOpen = true; _search.Focus(); };
        _search.TextChanged += (_, _) => Filter();
        _search.KeyDown += (_, e) => { if (e.Key == Key.Down && _rows.Children.FirstOrDefault() is RadioButton first) { first.Focus(); e.Handled = true; } };
    }
    private void Filter()
    {
        _rows.Children.Clear();
        foreach (var code in _items.Where(c => FoxUi.CountryLabel(c).Contains(_search.Text?.Trim() ?? "", StringComparison.CurrentCultureIgnoreCase))) {
            var row = new RadioButton { GroupName = "FoxCountries", IsChecked = Equals(code, _selected), Content = CountryRow(code, true), HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch, MinHeight = 48, Padding = new Thickness(8) };
            row.Classes.Add("DicodeNav");
            Avalonia.Automation.AutomationProperties.SetName(row, FoxUi.CountryLabel(code));
            row.Click += (_, _) => { SelectedItem = code; _popup.IsOpen = false; _button.Focus(); };
            _rows.Children.Add(row);
        }
    }
}
