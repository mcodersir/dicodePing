using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace AvaloniaApp
{
    public class MainViewModel : INotifyPropertyChanged
    {
        #region Text

        private string _text = string.Empty;

        public string Text
        {
            get => _text;
            set
            {
                if (_text != value)
                {
                    _text = value;
                    OnPropertyChanged(nameof(Text));
                }
            }
        }

        #endregion Text

        public event PropertyChangedEventHandler? PropertyChanged;

        protected virtual void OnPropertyChanged([CallerMemberName] string propertyName = null) =>
          PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(propertyName));
    }
}