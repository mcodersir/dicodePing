# Linux desktop and TUN

Start DicodePing as your ordinary desktop user. Do not run the GUI with `sudo` or `sudo -E`: WebKit's sandbox needs a normal user and root may leave unwritable account/configuration files.

The portable ZIP needs GTK3, WebKitGTK 4.1 and XWayland. On Arch install `webkit2gtk-4.1 xorg-xwayland`; on Debian/Ubuntu install `libwebkit2gtk-4.1-0 xwayland`. A KDE Wayland session is supported through its XWayland display. The application selects GTK's X11 backend before initialization.

TUN elevates only its core through the application's existing password prompt. If using file capabilities instead, apply them to the *runtime copy* reported in diagnostics, for example:

```sh
sudo setcap cap_net_admin,cap_net_raw,cap_net_bind_service=+ep "$HOME/.local/share/DicodePing/bin/xray/xray"
sudo setcap cap_net_admin,cap_net_raw,cap_net_bind_service=+ep "$HOME/.local/share/DicodePing/bin/sing_box/sing-box"
```

Only do this for binaries you trust. The launcher detects the required capabilities before starting a TUN core. An unchanged binary is preserved across application upgrades, including its capabilities. Replacing a binary with a different version removes Linux capabilities; reapply them or use the in-app core password prompt.

If a previous root launch left root-owned data, quit the application, then restore ownership of **your own** data directory:

```sh
sudo chown -R "$(id -u):$(id -g)" "$HOME/.local/share/DicodePing"
```

The installation's `bin` is the bundled source; `~/.local/share/DicodePing/bin` is the active runtime when local app data mode is enabled. On a new application version, changed bundled files are installed; user-added files and unchanged binaries are retained. sing-box is bundled and is no longer deleted at startup.

Xray's native TUN has its own fixed network stack. The gvisor/system/mixed Stack option applies to the independent sing-box route; adding an unsupported `stack` field to Xray would not select that stack.
