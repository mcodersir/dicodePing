from installer_ui_controls import is_install_source_toggle
# Captured from the failing Android 15 native Settings accessibility tree.
compose = {'class': 'android.view.View', 'resource-id': '', 'checkable': 'true', 'checked': 'false', 'clickable': 'true'}
classic = {'class': 'android.widget.Switch', 'resource-id': 'android:id/switch_widget', 'checkable': 'true', 'checked': 'false'}
label = {'class': 'android.widget.TextView', 'text': 'Allow from this source', 'checkable': 'false'}
assert is_install_source_toggle(compose)
assert is_install_source_toggle(classic)
assert not is_install_source_toggle(label)
print('PASS actual Compose Settings row and classic Switch; labels are not toggles')
