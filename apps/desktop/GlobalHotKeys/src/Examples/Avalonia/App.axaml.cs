using System;
using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Avalonia.Threading;
using GlobalHotKeys;

namespace AvaloniaApp
{
    public class App : Application
    {
        public override void Initialize()
        {
            AvaloniaXamlLoader.Load(this);
        }

        public override void OnFrameworkInitializationCompleted()
        {
            if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
            {
                var hotKeyManager = new HotKeyManager();
                var hotKeySubscription = hotKeyManager.Register(VirtualKeyCode.KEY_1, Modifiers.Shift);

                desktop.Exit += (sender, args) =>
                {
                    hotKeySubscription.Dispose();
                    hotKeyManager.Dispose();
                };

                var mainViewModel = new MainViewModel();

                hotKeyManager.HotKeyPressed += hotKey =>
                {
                    Dispatcher.UIThread.Post(() =>
                    {
                        mainViewModel.Text += $"hotKey: Id = {hotKey.Id}, Key = {hotKey.Key}, Modifiers = {hotKey.Modifiers}{Environment.NewLine}";
                    });
                };
                desktop.MainWindow =
                  new MainWindow
                  {
                      DataContext = mainViewModel
                  };
            }

            base.OnFrameworkInitializationCompleted();
        }
    }
}
