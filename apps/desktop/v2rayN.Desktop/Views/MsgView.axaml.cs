using System.Collections.Specialized;
using v2rayN.Desktop.Common;

namespace v2rayN.Desktop.Views;

public partial class MsgView : ReactiveUserControl<MsgViewModel>
{
    public MsgView()
    {
        InitializeComponent();

        this.WhenActivated(disposables =>
        {
            this.Bind(ViewModel, vm => vm.MsgFilter, v => v.cmbMsgFilter.Text).DisposeWith(disposables);
            this.Bind(ViewModel, vm => vm.AutoRefresh, v => v.togAutoRefresh.IsChecked).DisposeWith(disposables);

            ViewModel?.LogItems.CollectionChanged += LogItems_CollectionChanged;
            ScrollToEnd();
        });
    }

    private void LogItems_CollectionChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        if (e.Action == NotifyCollectionChangedAction.Add && (togScrollToEnd.IsChecked ?? true))
        {
            ScrollToEnd();
        }
    }

    private void ScrollToEnd()
    {
        Dispatcher.UIThread.Post(() =>
        {
            if (ViewModel?.LogItems.Count > 0)
            {
                lstLog.ScrollIntoView(ViewModel.LogItems[^1]);
            }
        }, DispatcherPriority.Background);
    }

    public void ClearMsg()
    {
        ViewModel?.LogItems.Clear();
    }

    private async void menuMsgViewCopyAll_Click(object? sender, RoutedEventArgs e)
    {
        var lines = ViewModel?.LogItems
            .Select(item => $"{item.Time} {item.Level}  {item.Content}") ?? [];
        await AvaUtils.SetClipboardData(this, string.Join(Environment.NewLine, lines));
    }

    private void menuMsgViewClear_Click(object? sender, RoutedEventArgs e)
    {
        ClearMsg();
    }
}
