namespace ServiceLib.Base;

public class BulkObservableCollection<T> : ObservableCollection<T>
{
    private bool _suppressNotification = false;

    protected override void OnCollectionChanged(NotifyCollectionChangedEventArgs e)
    {
        if (!_suppressNotification)
        {
            base.OnCollectionChanged(e);
        }
    }

    protected override void OnPropertyChanged(PropertyChangedEventArgs e)
    {
        if (!_suppressNotification)
        {
            base.OnPropertyChanged(e);
        }
    }

    public void AddRange(IEnumerable<T>? collection)
    {
        if (collection == null)
        {
            return;
        }

        _suppressNotification = true;
        try
        {
            foreach (var item in collection)
            {
                Add(item);
            }
        }
        finally
        {
            _suppressNotification = false;
            OnPropertyChanged(new PropertyChangedEventArgs(nameof(Count)));
            OnPropertyChanged(new PropertyChangedEventArgs("Item[]"));
            OnCollectionChanged(new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Reset));
        }
    }

    /// <summary>
    /// Replaces the complete snapshot with one Reset notification. Calling
    /// Clear followed by AddRange emits an observable empty state and makes the
    /// desktop grid flash/disappear while tests are completing.
    /// </summary>
    public void ReplaceAll(IEnumerable<T>? collection)
    {
        if (collection == null)
        {
            return;
        }

        _suppressNotification = true;
        try
        {
            Clear();
            foreach (var item in collection)
            {
                Add(item);
            }
        }
        finally
        {
            _suppressNotification = false;
            OnPropertyChanged(new PropertyChangedEventArgs(nameof(Count)));
            OnPropertyChanged(new PropertyChangedEventArgs("Item[]"));
            OnCollectionChanged(new NotifyCollectionChangedEventArgs(NotifyCollectionChangedAction.Reset));
        }
    }

    public bool Replace(T oldItem, T newItem)
    {
        var index = Items.IndexOf(oldItem);
        if (index < 0)
        {
            return false;
        }

        Items[index] = newItem;

        OnPropertyChanged(new PropertyChangedEventArgs("Item[]"));
        OnCollectionChanged(new NotifyCollectionChangedEventArgs(
            NotifyCollectionChangedAction.Replace,
            newItem,
            oldItem,
            index));

        return true;
    }
}
