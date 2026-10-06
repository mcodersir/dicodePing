using v2rayN.Desktop.Base;

namespace v2rayN.Desktop.Views;

public partial class SpoSourcesWindow : WindowBase<SanctionsServicesViewModel>
{
    public SpoSourcesWindow()
    {
        InitializeComponent();

        EditorView.btnCancel.Click += (_, _) => Close(false);
        EditorView.btnSave.Click += (_, _) => ViewModel?.SaveCmd.Execute().Subscribe(result => Close(result));
    }
}
