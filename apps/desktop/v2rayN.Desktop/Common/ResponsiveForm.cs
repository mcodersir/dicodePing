namespace v2rayN.Desktop.Common;

/// <summary>Keep settings labels, inputs and help readable on narrow windows.</summary>
public sealed class ResponsiveForm : AvaloniaObject
{
    public static readonly AttachedProperty<bool> EnabledProperty = AvaloniaProperty.RegisterAttached<ResponsiveForm, Grid, bool>("Enabled");
    public static bool GetEnabled(Grid grid) => grid.GetValue(EnabledProperty);
    public static void SetEnabled(Grid grid, bool enabled) => grid.SetValue(EnabledProperty, enabled);
    static ResponsiveForm() => EnabledProperty.Changed.AddClassHandler<Grid>((grid, _) =>
    {
        if (!GetEnabled(grid)) return;
        var initialized = false;
        grid.Loaded += (_, _) =>
        {
            if (initialized) return;
            initialized = true;
            var columns = grid.ColumnDefinitions.Select(c => c.Width).ToArray();
            var rows = grid.RowDefinitions.Select(r => r.Height).ToArray();
            var children = grid.Children.Select(c => (Control: c, Row: Grid.GetRow(c), Column: Grid.GetColumn(c), Span: Grid.GetColumnSpan(c), Width: c.Width)).ToArray();
            bool? previous = null;
            void Update(double width)
            {
                if (width <= 0) return;
                var compact = width < 620;
                if (previous == compact) return;
                previous = compact;
                grid.ColumnDefinitions.Clear();
                foreach (var length in compact ? new[] { GridLength.Star } : columns)
                    grid.ColumnDefinitions.Add(new ColumnDefinition(length));
                grid.RowDefinitions.Clear();
                foreach (var length in compact ? Enumerable.Repeat(GridLength.Auto, Math.Max(rows.Length, children.Max(c => c.Row) + 1) * columns.Length) : rows)
                    grid.RowDefinitions.Add(new RowDefinition(length));
                foreach (var item in children)
                {
                    Grid.SetRow(item.Control, compact ? item.Row * columns.Length + item.Column : item.Row);
                    Grid.SetColumn(item.Control, compact ? 0 : item.Column);
                    Grid.SetColumnSpan(item.Control, compact ? 1 : item.Span);
                    item.Control.Width = compact ? double.NaN : item.Width;
                    if (item.Control is TextBlock label) label.TextWrapping = TextWrapping.Wrap;
                }
            }
            grid.SizeChanged += (_, e) => Update(e.NewSize.Width);
            Update(grid.Bounds.Width);
        };
    });
}
