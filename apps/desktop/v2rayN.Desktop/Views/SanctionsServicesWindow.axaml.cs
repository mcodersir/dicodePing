using v2rayN.Desktop.Base;

namespace v2rayN.Desktop.Views;

public partial class SanctionsServicesWindow : WindowBase<SanctionsServicesViewModel>
{
    public SanctionsServicesWindow()
    {
        InitializeComponent();

        btnCancel.Click += (_, _) => Close(false);
        btnSave.Click += (_, _) => ViewModel?.SaveCmd.Execute().Subscribe(result => Close(result));

        this.WhenActivated(disposables =>
        {
            this.OneWayBind(ViewModel, x => x.Rows, v => v.lstRows.ItemsSource).DisposeWith(disposables);
            this.BindCommand(ViewModel, x => x.AddRowCmd, v => v.btnAdd).DisposeWith(disposables);
            this.BindCommand(ViewModel, x => x.ResetDefaultsCmd, v => v.btnReset).DisposeWith(disposables);
        });
    }
}
