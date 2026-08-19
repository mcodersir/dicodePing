using System;
using System.Windows;
using GlobalHotKeys;

namespace Wpf
{
    /// <summary>
    /// Interaction logic for App.xaml
    /// </summary>
    public partial class App : Application
    {
        private HotKeyManager _hotKeyManager;
        private IDisposable _shift1;
        private IDisposable _shift2;
        private IDisposable _subscription;

        private void App_OnStartup(object sender, StartupEventArgs e)
        {
            _hotKeyManager = new HotKeyManager();
            _shift1 = _hotKeyManager.Register(VirtualKeyCode.KEY_1, Modifiers.Shift);
            _shift2 = _hotKeyManager.Register(VirtualKeyCode.KEY_2, Modifiers.Shift);

            var mainViewModel = new MainViewModel();
            this.MainWindow = new MainWindow { DataContext = mainViewModel };
            this.MainWindow.Show();

            _hotKeyManager.HotKeyPressed += hotKey =>
            {
                Application.Current.Dispatcher.BeginInvoke(() =>
                {
                    mainViewModel.Text += $"hotKey: Id = {hotKey.Id}, Key = {hotKey.Key}, Modifiers = {hotKey.Modifiers}{Environment.NewLine}";
                });
            };
        }

        private void App_OnExit(object sender, ExitEventArgs e)
        {
            _subscription.Dispose();
            _shift1.Dispose();
            ((IDisposable)_hotKeyManager).Dispose();
        }
    }
}
