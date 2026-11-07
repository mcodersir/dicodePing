using Avalonia.Controls.Primitives;
using Avalonia.Controls.Templates;
using Avalonia.Layout;

namespace v2rayN.Desktop.Views;

/// <summary>Keyboard-accessible country search with a bounded, scrolling menu.</summary>
public sealed class FoxCountryPicker : UserControl
{
    private readonly Button _button = new() { HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch };
    private readonly TextBox _search = new() { PlaceholderText = FoxUi.T("جستجوی کشور یا کد", "Search country or code") };
    private readonly ListBox _list = new() { MaxHeight = 300, MinHeight = 80 };
    private readonly Popup _popup;
    private IEnumerable<string> _items = [];
    private object? _selected;
    public event EventHandler? SelectionChanged;
    public bool IsDropDownOpen { get => _popup.IsOpen; set { _popup.Width = Math.Max(260, Bounds.Width); _popup.IsOpen = value; } }
    public string SearchText { get => _search.Text ?? ""; set => _search.Text = value; }
    public int VisibleCountryCount => (_list.ItemsSource as string[])?.Length ?? 0;

    public IDataTemplate? ItemTemplate { get => _list.ItemTemplate; set => _list.ItemTemplate = value; }
    public IEnumerable<string> ItemsSource { get => _items; set { _items = value; Filter(); } }
    public int SelectedIndex { set => SelectedItem = _items.ElementAtOrDefault(value); }
    public object? SelectedItem {
        get => _selected;
        set {
            if (Equals(value, _selected)) return;
            _selected = value;
            _button.Content = new TextBlock { Text = FoxUi.CountryLabel(value?.ToString()) + "  ⌄", TextWrapping = TextWrapping.Wrap };
            SelectionChanged?.Invoke(this, EventArgs.Empty);
        }
    }
    public FoxCountryPicker()
    {
        _popup = new Popup { PlacementTarget = _button, IsLightDismissEnabled = true, Placement = PlacementMode.Bottom,
            Child = new Border { Padding = new Thickness(12), CornerRadius = new CornerRadius(14), BorderThickness = new Thickness(1),
                Background = Application.Current?.FindResource("DicodeSurfaceElevated") as IBrush,
                BorderBrush = Application.Current?.FindResource("DicodeTextSecondary") as IBrush,
                Child = new StackPanel { Spacing = 10, Children = { _search, _list } } } };
        Content = new Panel { Children = { _button, _popup } };
        _button.Click += (_, _) => { _popup.Width = Math.Max(260, Bounds.Width); _search.Text = ""; Filter(); _popup.IsOpen = true; _search.Focus(); };
        _search.TextChanged += (_, _) => Filter();
        _list.SelectionChanged += (_, _) => { if (_list.SelectedItem is string code) { SelectedItem = code; _popup.IsOpen = false; _button.Focus(); } };
        _search.KeyDown += (_, e) => { if (e.Key == Avalonia.Input.Key.Down) { _list.Focus(); _list.SelectedIndex = 0; e.Handled = true; } };
    }
    private void Filter() => _list.ItemsSource = _items.Where(code => FoxUi.CountryLabel(code).Contains(_search.Text?.Trim() ?? "", StringComparison.CurrentCultureIgnoreCase)).ToArray();
}
