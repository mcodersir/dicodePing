using v2rayN.Desktop.Common;

namespace v2rayN.Desktop.Views;

public partial class SpoSourcesView : ReactiveUserControl<SpoSourcesViewModel>
{
    public SpoSourcesView()
    {
        InitializeComponent();

        this.WhenActivated(disposables =>
        {
            lstRows.ItemsSource = ViewModel?.VisibleRows;
            this.Bind(ViewModel, x => x.SearchText, v => v.txtSearch.Text).DisposeWith(disposables);
            this.BindCommand(ViewModel, x => x.AddRowCmd, v => v.btnAdd).DisposeWith(disposables);
            this.BindCommand(ViewModel, x => x.EnableAllCmd, v => v.btnEnableAll).DisposeWith(disposables);
            this.BindCommand(ViewModel, x => x.ResetDefaultsCmd, v => v.btnReset).DisposeWith(disposables);
        });
    }
}
