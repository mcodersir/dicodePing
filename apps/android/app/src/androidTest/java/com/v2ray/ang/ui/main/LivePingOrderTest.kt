package com.v2ray.ang.ui.main

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyGridState
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class LivePingOrderTest {
    @get:Rule val compose = createComposeRule()
    @Test fun listShowsNewBestAtTheTopAndRespectsManualScrolling() = exercise(false)
    @Test fun gridShowsNewBestAtTheTopAndRespectsManualScrolling() = exercise(true)
    private fun exercise(grid: Boolean) {
        var ids by mutableStateOf((0 until 100).map(Int::toString))
        val list = LazyListState()
        val tiles = LazyGridState()
        compose.setContent {
            if (grid) {
                FollowPingGridResults(true, ids, tiles)
                LazyVerticalGrid(columns = GridCells.Fixed(2), state = tiles, modifier = Modifier.fillMaxSize().testTag("results")) {
                    items(ids, key = { it }) { Text(it, Modifier.height(70.dp)) }
                }
            } else {
                FollowPingListResults(true, ids, list)
                LazyColumn(state = list, modifier = Modifier.fillMaxSize().testTag("results")) {
                    items(ids, key = { it }) { Text(it, Modifier.height(70.dp)) }
                }
            }
        }
        compose.runOnIdle { ids = listOf("9") + ids.filterNot { it == "9" } }
        compose.waitForIdle()
        compose.runOnIdle {
            assertEquals(0, if (grid) tiles.firstVisibleItemIndex else list.firstVisibleItemIndex)
            assertEquals("9", if (grid) tiles.layoutInfo.visibleItemsInfo.first().key else list.layoutInfo.visibleItemsInfo.first().key)
        }
        compose.onNodeWithTag("results").performTouchInput { swipeUp() }
        compose.waitForIdle()
        var anchor: Any? = null
        compose.runOnIdle {
            assertTrue((if (grid) tiles.firstVisibleItemIndex else list.firstVisibleItemIndex) > 0)
            anchor = if (grid) tiles.layoutInfo.visibleItemsInfo.first().key else list.layoutInfo.visibleItemsInfo.first().key
            ids = listOf("90", "91") + ids.filterNot { it == "90" || it == "91" }
        }
        compose.waitForIdle()
        compose.runOnIdle {
            assertEquals(anchor, if (grid) tiles.layoutInfo.visibleItemsInfo.first().key else list.layoutInfo.visibleItemsInfo.first().key)
        }
    }
}
