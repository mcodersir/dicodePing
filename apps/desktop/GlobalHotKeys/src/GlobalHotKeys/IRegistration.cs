namespace GlobalHotKeys;

public interface IRegistration : IDisposable
{
    bool IsSuccessful { get; }

    int Id { get; }
}