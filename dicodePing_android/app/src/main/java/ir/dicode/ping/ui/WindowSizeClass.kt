package ir.dicode.ping.ui

import android.content.res.Resources

enum class DicodeWindowSizeClass { COMPACT, MEDIUM, EXPANDED }

fun Resources.dicodeWindowSizeClass(): DicodeWindowSizeClass = when {
    configuration.screenWidthDp >= 840 -> DicodeWindowSizeClass.EXPANDED
    configuration.screenWidthDp >= 600 -> DicodeWindowSizeClass.MEDIUM
    else -> DicodeWindowSizeClass.COMPACT
}
