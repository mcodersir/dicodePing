package com.v2ray.ang.ui.server

import androidx.activity.viewModels
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.v2ray.ang.R
import com.v2ray.ang.enums.EConfigType
import com.v2ray.ang.extension.moveItem
import com.v2ray.ang.ui.base.BaseComponentActivity
import com.v2ray.ang.ui.base.EditorLoading
import com.v2ray.ang.ui.base.EditorOutcomeEffect
import com.v2ray.ang.ui.compose.AppTopBar
import com.v2ray.ang.ui.compose.DeleteConfirmDialog
import com.v2ray.ang.ui.compose.FormDropdownField
import com.v2ray.ang.ui.compose.FormTextField
import com.v2ray.ang.ui.compose.reorderableDragHandle
import com.v2ray.ang.ui.compose.verticalScrollbar
import sh.calvin.reorderable.ReorderableItem
import sh.calvin.reorderable.rememberReorderableLazyListState
import java.util.UUID

class ServerProxyChainActivity : BaseComponentActivity() {

    private val editGuid by lazy { intent.getStringExtra("guid").orEmpty() }
    private val subscriptionId by lazy { intent.getStringExtra("subscriptionId") }

    /** PattNG: the save, which outlives this activity when it is recreated, see [ServerProxyChainViewModel]. */
    private val viewModel: ServerProxyChainViewModel by viewModels {
        viewModelFactory {
            initializer {
                ServerProxyChainViewModel(application, ProfileEditorRepository(), editGuid, subscriptionId, intent.getBooleanExtra("isRunning", false))
            }
        }
    }

    @Composable
    override fun ScreenContent() {
        // PattNG: read off the main thread, see ProfileEditorViewModel.isRunning; no delete is offered until it is known.
        val running by viewModel.isRunning.collectAsStateWithLifecycle()
        val opened by viewModel.opened.collectAsStateWithLifecycle()
        EditorOutcomeEffect(
            viewModel = viewModel,
            onSaved = { guid ->
                ProfileEditorResult.run {
                    finishSaved(
                        guid = guid,
                        restartService = viewModel.isRunning.value == true
                    )
                }
            },
            onDeleted = {
                ProfileEditorResult.run {
                    finishDeleted(editGuid)
                }
            }
        )
        // PattNG: the chain and the names of the profiles are read off the main thread; until they are, the screen waits.
        val chain = opened
        if (chain == null) {
            EditorLoading(EConfigType.PROXYCHAIN.toString()) { finish() }
            return
        }
        ProxyChainScreen(
            editGuid = editGuid,
            isRunning = running != false,
            initialRemarks = chain.remarks,
            initialMembers = chain.members,
            allRemarks = chain.profileNames,
            onBackClick = { finish() },
            onSave = { remarks, members -> viewModel.save(remarks, members) },
            onDelete = { viewModel.delete() }
        )
    }

    /**
     * PattNG: the screen closes only once the save or the delete that runs has written, telling the screen it returns
     * to what it did, see [com.v2ray.ang.ui.base.EditorViewModel.leaveScreen].
     */
    override fun finish() {
        if (viewModel.leaveScreen()) super.finish()
    }
}

@Composable
fun ProxyChainScreen(
    editGuid: String,
    isRunning: Boolean,
    initialRemarks: String,
    initialMembers: List<String>,
    allRemarks: List<String>,
    onBackClick: () -> Unit,
    onSave: (String, List<String>) -> Unit,
    onDelete: () -> Unit
) {
    var remarks by rememberSaveable { mutableStateOf(initialRemarks) }
    var isRemarksError by rememberSaveable { mutableStateOf(false) }
    var members by rememberSaveable { mutableStateOf(initialMembers) }
    var memberKeys by rememberSaveable { mutableStateOf(List(initialMembers.size) { UUID.randomUUID().toString() }) }
    var showProfileDeleteConfirm by remember { mutableStateOf(false) }
    var memberToDeleteKey by rememberSaveable { mutableStateOf<String?>(null) }
    val showDelete = editGuid.isNotEmpty() && !isRunning

    val lazyListState = rememberLazyListState()
    val reorderableState = rememberReorderableLazyListState(lazyListState) { from, to ->
        val fromIndex = memberKeys.indexOf(from.key)
        val toIndex = memberKeys.indexOf(to.key)
        if (fromIndex != -1 && toIndex != -1) {
            val reordered = members.toMutableList()
            val reorderedKeys = memberKeys.toMutableList()
            if (reordered.moveItem(fromIndex, toIndex)) {
                reorderedKeys.moveItem(fromIndex, toIndex)
                members = reordered
                memberKeys = reorderedKeys
            }
        }
    }

    Scaffold(
        contentWindowInsets = WindowInsets(0),
        topBar = {
            AppTopBar(
                title = EConfigType.PROXYCHAIN.toString(),
                onBackClick = onBackClick,
                actions = {
                    if (showDelete) {
                        IconButton(onClick = { showProfileDeleteConfirm = true }) {
                            Icon(painterResource(R.drawable.ic_delete_24dp), contentDescription = stringResource(R.string.acc_delete))
                        }
                    }
                    IconButton(onClick = {
                        val remarksErr = remarks.isBlank()
                        isRemarksError = remarksErr

                        val hasError = remarksErr
                        if (!hasError) {
                            onSave(remarks, members)
                        }
                    }) {
                        Icon(painterResource(R.drawable.ic_fab_check), contentDescription = stringResource(R.string.acc_save))
                    }
                }
            )
        },
        floatingActionButton = {
            FloatingActionButton(
                onClick = {
                    members = members + ""
                    memberKeys = memberKeys + UUID.randomUUID().toString()
                },
                modifier = Modifier
                    .offset(y = -20.dp)
                    .navigationBarsPadding()
            ) {
                Icon(painterResource(R.drawable.ic_add_24dp), contentDescription = stringResource(R.string.acc_add_member))
            }
        }
    ) { innerPadding ->
        LazyColumn(
            state = lazyListState,
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .consumeWindowInsets(innerPadding)
                .imePadding()
                .verticalScrollbar(lazyListState),
            contentPadding = PaddingValues(
                top = 8.dp,
                start = 16.dp,
                end = 16.dp,
                bottom = 36.dp + WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()
            )
        ) {
            item(key = "remarks_field") {
                FormTextField(
                    label = stringResource(R.string.server_lab_remarks),
                    value = remarks,
                    onValueChange = { remarks = it },
                    isError = isRemarksError
                )
            }

            item {
                Text(
                    text = stringResource(R.string.server_proxy_chain_members),
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.padding(start = 16.dp, top = 8.dp, bottom = 8.dp)
                )
            }

            itemsIndexed(items = members, key = { index, _ -> memberKeys[index] }) { index, member ->
                val memberKey = memberKeys[index]
                ReorderableItem(reorderableState, key = memberKey) { isDragging ->
                    val elevation by animateDpAsState(if (isDragging) 4.dp else 0.dp)
                    Surface(shadowElevation = elevation) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .then(with(this) { reorderableDragHandle() })
                                .padding(horizontal = 4.dp, vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                "${index + 1}",
                                modifier = Modifier
                                    .padding(start = 16.dp)
                                    .width(10.dp)
                            )
                            FormDropdownField(
                                label = stringResource(R.string.server_lab_remarks),
                                placeholder = stringResource(R.string.server_proxy_chain_member_unselected),
                                value = member,
                                options = allRemarks,
                                onValueChange = { newVal ->
                                    members = members.toMutableList().also { it[index] = newVal }
                                },
                                editable = true,
                                modifier = Modifier.weight(1f)
                            )
                            IconButton(onClick = {
                                if (member.isBlank()) {
                                    val (remainingMembers, remainingKeys) = withoutProxyChainMember(members, memberKeys, memberKey)
                                    members = remainingMembers
                                    memberKeys = remainingKeys
                                } else {
                                    memberToDeleteKey = memberKey
                                }
                            }) {
                                Icon(
                                    painterResource(R.drawable.ic_delete_24dp),
                                    contentDescription = stringResource(R.string.acc_remove)
                                )
                            }
                        }
                    }
                }
            }
        }
    }

    if (showProfileDeleteConfirm) {
        DeleteConfirmDialog(
            message = stringResource(R.string.confirm_delete_profile),
            itemName = initialRemarks,
            onConfirm = { showProfileDeleteConfirm = false; onDelete() },
            onDismiss = { showProfileDeleteConfirm = false }
        )
    }
    memberToDeleteKey?.let { memberKey ->
        DeleteConfirmDialog(
            message = stringResource(R.string.confirm_delete_proxy_chain_member),
            itemName = members.getOrNull(memberKeys.indexOf(memberKey)).orEmpty(),
            onConfirm = {
                val (remainingMembers, remainingKeys) = withoutProxyChainMember(members, memberKeys, memberKey)
                members = remainingMembers
                memberKeys = remainingKeys
                memberToDeleteKey = null
            },
            onDismiss = { memberToDeleteKey = null }
        )
    }
}
