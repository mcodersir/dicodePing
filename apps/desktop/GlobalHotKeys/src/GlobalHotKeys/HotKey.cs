namespace GlobalHotKeys;

public class HotKey
{
    public int Id { get; set; }
    public Modifiers Modifiers { get; set; }
    public VirtualKeyCode Key { get; set; }
}