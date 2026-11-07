"""Recognize native and Compose accessibility controls in the isolated installer test."""
def is_install_source_toggle(attributes):
    # Android 15+ Settings can expose the entire Compose row as a checkable
    # android.view.View, without a Switch class or resource id.
    return (attributes.get('checkable') == 'true'
            or 'Switch' in attributes.get('class', '')
            or 'switch_widget' in attributes.get('resource-id', ''))
