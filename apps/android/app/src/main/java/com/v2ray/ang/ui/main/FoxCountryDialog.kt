package com.v2ray.ang.ui.main

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp

@Composable
internal fun FoxCountryDialog(countries: List<String>, label: (String) -> String, fa: Boolean,
                              onDismiss: () -> Unit, onSelect: (String) -> Unit, selected: String = "REC") {
    var search by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = onDismiss,
        title = { Text(if (fa) "انتخاب کشور" else "Choose location") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(value = search, onValueChange = { search = it },
                    modifier = Modifier.fillMaxWidth().testTag("country-search"), singleLine = true, shape = androidx.compose.foundation.shape.RoundedCornerShape(12.dp),
                    label = { Text(if (fa) "جستجوی کشور یا کد" else "Search country or code") })
                LazyColumn(Modifier.fillMaxWidth().heightIn(max = 340.dp)) {
                    items(countries.filter { label(it).contains(search.trim(), ignoreCase = true) || it.contains(search.trim(), ignoreCase = true) }) { value ->
                        TextButton(modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp).testTag("country-$value"), onClick = { onSelect(value) }) {
                            FoxFlag(value)
                            Spacer(Modifier.width(12.dp))
                            Text(label(value), modifier = Modifier.weight(1f))
                            RadioButton(selected = value == selected, onClick = null)
                        }
                    }
                }
            }
        }, confirmButton = { TextButton(onClick = onDismiss) { Text(if (fa) "بستن" else "Close") } })
}
