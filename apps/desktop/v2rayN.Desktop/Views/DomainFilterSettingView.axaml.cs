using v2rayN.Desktop.Base;

namespace v2rayN.Desktop.Views;

public partial class DomainFilterSettingView : ReactiveUserControl<DomainFilterSettingViewModel>
{
    public event EventHandler? Applied;

    public DomainFilterSettingView()
    {
        InitializeComponent();
        ViewModel = new DomainFilterSettingViewModel();
        btnCancel.Click += (_, _) => ResetForm();
        this.WhenActivated(disposables =>
        {
            this.Bind(ViewModel, x => x.OnlyListedDomains, v => v.togOnly.IsChecked).DisposeWith(disposables);
            this.Bind(ViewModel, x => x.BypassListedDomains, v => v.togBypass.IsChecked).DisposeWith(disposables);
            this.Bind(ViewModel, x => x.Domains, v => v.txtDomains.Text).DisposeWith(disposables);
            ViewModel.SaveCmd.Subscribe(result => ApplyChanges()).DisposeWith(disposables);
            this.BindCommand(ViewModel, x => x.SaveCmd, v => v.btnSave).DisposeWith(disposables);
        });
    }
    private void ResetForm() => ViewModel = new DomainFilterSettingViewModel();

    private void ApplyChanges()
    {
        NoticeManager.Instance.Enqueue(ResUI.OperationSuccess);
        Applied?.Invoke(this, EventArgs.Empty);

    }
}
