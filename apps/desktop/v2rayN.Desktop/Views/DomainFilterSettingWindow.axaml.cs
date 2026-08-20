using v2rayN.Desktop.Base;

namespace v2rayN.Desktop.Views;

public partial class DomainFilterSettingWindow : WindowBase<DomainFilterSettingViewModel>
{
    public DomainFilterSettingWindow()
    {
        InitializeComponent();
        btnCancel.Click += (_, _) => Close(false);
        this.WhenActivated(disposables =>
        {
            this.Bind(ViewModel, x => x.OnlyListedDomains, v => v.togOnly.IsChecked).DisposeWith(disposables);
            this.Bind(ViewModel, x => x.BypassListedDomains, v => v.togBypass.IsChecked).DisposeWith(disposables);
            this.Bind(ViewModel, x => x.Domains, v => v.txtDomains.Text).DisposeWith(disposables);
            ViewModel.SaveCmd.Subscribe(result => Close(result)).DisposeWith(disposables);
            this.BindCommand(ViewModel, x => x.SaveCmd, v => v.btnSave).DisposeWith(disposables);
        });
    }
}
