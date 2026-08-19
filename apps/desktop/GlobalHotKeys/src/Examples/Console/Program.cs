using System;
using GlobalHotKeys;

void HotKeyPressed(HotKey hotKey) =>
  Console.WriteLine($"HotKey Pressed: Id = {hotKey.Id}, Key = {hotKey.Key}, Modifiers = {hotKey.Modifiers}");

using var hotKeyManager = new HotKeyManager();
hotKeyManager.HotKeyPressed += HotKeyPressed;
using var shift1 = hotKeyManager.Register(VirtualKeyCode.KEY_1, Modifiers.Shift);
using var ctrl1 = hotKeyManager.Register(VirtualKeyCode.KEY_1, Modifiers.Control);

Console.WriteLine("Listening for HotKeys...");
Console.ReadLine();
