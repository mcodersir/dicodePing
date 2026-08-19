# README
GlobalHotKeys is a tiny .NET Library for registering global HotKeys on Windows, written by Martin Kramer (https://lostindetails.com)

The library allows an application to react to Key Press events even if the application does not currently have focus.

## Additional Info
For additional info please visit: https://lostindetails.com/articles/Global-HotKeys-for-Windows-Applications

## Installation
Install the nuget package via `dotnet add package`
```bat
dotnet add package GlobalHotKeys.Windows
```

## Example Usage
Please take a look at the examples in the `src/Examples` folder.

Here is an example for a C# Console Application:

```cs
using System;
using GlobalHotKeys;

void HotKeyPressed(HotKey hotKey) =>
  Console.WriteLine($"HotKey Pressed: Id = {hotKey.Id}, Key = {hotKey.Key}, Modifiers = {hotKey.Modifiers}");

using var hotKeyManager = new HotKeyManager();
using var subscription = hotKeyManager.HotKeyPressed.Subscribe(HotKeyPressed);
using var shift1 = hotKeyManager.Register(VirtualKeyCode.KEY_1, Modifiers.Shift);
using var ctrl1 = hotKeyManager.Register(VirtualKeyCode.KEY_1, Modifiers.Control);

Console.WriteLine("Listening for HotKeys...");
Console.ReadLine();
```

## Source POI
- C#
- Examples for
  - WinForms
  - Wpf
  - Console
  - AvaloniaUI
- Implements a simple Message Loop

## License
This library is dual Licensed under the WTFPL or MIT.
That means you are free to choose either the WTFPL or the MIT License.The reason for giving you the option is that the even though the WTFPL is the more permissive license, the MIT License is better known.

### COPYRIGHT - WTFPL
Copyright © 2021 Martin Kramer (https://lostindetails.com)
This work is free. You can redistribute it and/or modify it under the
terms of the Do What The Fuck You Want To Public License, Version 2,
as published by Sam Hocevar. See http://www.wtfpl.net/ for more details.

### COPYRIGHT - MIT
Copyright © 2021 Martin Kramer (https://lostindetails.com)

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.