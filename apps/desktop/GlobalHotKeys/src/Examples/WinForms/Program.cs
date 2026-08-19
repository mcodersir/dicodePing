using System;
using System.Windows.Forms;
using GlobalHotKeys;

namespace WinForms
{
    internal static class Program
    {
        /// <summary>
        ///  The main entry point for the application.
        /// </summary>
        [STAThread]
        private static void Main()
        {
            Application.SetHighDpiMode(HighDpiMode.SystemAware);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);

            using var hotKeyManager = new HotKeyManager();
            using var shift1 = hotKeyManager.Register(VirtualKeyCode.KEY_1, Modifiers.Shift);

            var form = new Form1();

            hotKeyManager.HotKeyPressed += hotKey =>
            {
                if (form.InvokeRequired)
                {
                    form.BeginInvoke(() =>
                    {
                        form.AppendText($"HotKey: Id = {hotKey.Id}, Key = {hotKey.Key}, Modifiers = {hotKey.Modifiers}{Environment.NewLine}");
                    });
                }
                else
                {
                    form.AppendText($"HotKey: Id = {hotKey.Id}, Key = {hotKey.Key}, Modifiers = {hotKey.Modifiers}{Environment.NewLine}");
                }
            };

            Application.Run(form);
        }
    }
}
