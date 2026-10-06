using v2rayN.Desktop.Base;

namespace v2rayN.Desktop.Views;

public partial class SanctionsServicesWindow : WindowBase<SanctionsServicesViewModel>
{
    public SanctionsServicesWindow()
    {
        InitializeComponent();

        btnCancel.Click += (_, _) => Close(false);
        btnSave.Click += (_, _) => ViewModel?.SaveCmd.Execute().Subscribe(result => Close(result));

        EditorView.btnCancel.Click += (_, _) => Close(false);
        EditorView.btnSave.Click += (_, _) => ViewModel?.SaveCmd.Execute().Subscribe(result => Close(result));
    }
}
