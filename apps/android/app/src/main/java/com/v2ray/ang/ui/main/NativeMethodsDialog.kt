package com.v2ray.ang.ui.main

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.v2ray.ang.R
import com.v2ray.ang.core.NativeProfileTemplates

@Composable
internal fun NativeMethodsDialog(onDismiss: () -> Unit, onImport: (String) -> Unit) {
    var kind by remember { mutableStateOf("snell") }
    var name by remember { mutableStateOf("") }; var server by remember { mutableStateOf("") }
    var port by remember { mutableStateOf("443") }; var user by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }; var extra by remember { mutableStateOf("") }
    var error by remember { mutableStateOf("") }; var expanded by remember { mutableStateOf(false) }
    val labels = listOf("Snell 4", "AnyTLS", "SSH", "Cisco / OpenConnect", "OpenVPN", "External helper · SOCKS5")
    AlertDialog(onDismissRequest = onDismiss, title = { Text(stringResource(R.string.native_methods_title)) },
        text = { Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(stringResource(R.string.native_methods_hint))
            Box { OutlinedButton(onClick = { expanded = true }, modifier = Modifier.fillMaxWidth()) { Text(labels[NativeProfileTemplates.kinds.indexOf(kind)]) }
                DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                    NativeProfileTemplates.kinds.forEachIndexed { i, k -> DropdownMenuItem(text = { Text(labels[i]) }, onClick = { kind = k; expanded = false; port = if (k == "socks") "1080" else if (k == "ssh") "22" else if (k == "openvpn-client") "1194" else "443" }) }
                }
            }
            OutlinedTextField(name, { name = it }, label = { Text(stringResource(R.string.native_connection_name)) }, singleLine = true)
            OutlinedTextField(server, { server = it }, label = { Text("Server / IP") }, singleLine = true)
            OutlinedTextField(port, { port = it.filter(Char::isDigit).take(5) }, label = { Text("Port") }, singleLine = true)
            if (kind in listOf("ssh", "openconnect", "openvpn-client", "socks")) OutlinedTextField(user, { user = it }, label = { Text("Username") }, singleLine = true)
            OutlinedTextField(password, { password = it }, label = { Text("Password / PSK") }, singleLine = true, visualTransformation = PasswordVisualTransformation())
            if (kind == "socks") Text(stringResource(R.string.native_external_hint))
            if (kind !in listOf("snell", "socks")) OutlinedTextField(extra, { extra = it }, label = { Text(when (kind) { "ssh" -> "SSH host key"; "openconnect", "openvpn-client" -> "CA certificate (PEM)"; else -> "TLS server name (SNI)" }) }, minLines = if (kind.startsWith("open")) 3 else 1)
            if (error.isNotBlank()) Text(error, color = MaterialTheme.colorScheme.error)
        } },
        confirmButton = { TextButton(onClick = {
            runCatching { NativeProfileTemplates.build(kind, server, port.toIntOrNull() ?: 0, user, password, extra, name) }
                .onSuccess { onImport(it); onDismiss() }.onFailure { error = it.message.orEmpty() }
        }) { Text(stringResource(R.string.native_save_connection)) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(android.R.string.cancel)) } })
}
