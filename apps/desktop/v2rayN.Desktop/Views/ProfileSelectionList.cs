namespace v2rayN.Desktop.Views;

public sealed class ProfileSelectionList : ListBox
{
    protected override Type StyleKeyOverride => typeof(ListBox);

    public override bool UpdateSelectionFromEvent(Control container, RoutedEventArgs args)
    {
        // Profile clicks extend the selection only through the platform's Ctrl/Command toggle.
        if (args is PointerEventArgs pointer &&
            !pointer.Handled &&
            !pointer.Properties.IsRightButtonPressed &&
            pointer.KeyModifiers.HasFlag(KeyModifiers.Shift) &&
            ShouldTriggerSelection(container, pointer) &&
            IndexFromContainer(container) is var index && index >= 0)
        {
            var command = OperatingSystem.IsMacOS() ? KeyModifiers.Meta : KeyModifiers.Control;
            UpdateSelection(index, toggleModifier: pointer.KeyModifiers.HasFlag(command));
            pointer.Handled = true;
            return true;
        }

        return base.UpdateSelectionFromEvent(container, args);
    }
}
