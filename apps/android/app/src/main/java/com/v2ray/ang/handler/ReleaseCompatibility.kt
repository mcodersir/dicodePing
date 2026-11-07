package com.v2ray.ang.handler

/** App release ordering; 4.9.991 follows the historical 4.9.98x hotfixes. */
internal object ReleaseCompatibility {
    fun compareVersions(first: String, second: String): Int {
        fun parts(value: String): List<Int> {
            val p = Regex("\\d+").findAll(value).map { it.value.toInt() }.toMutableList()
            if (p.size >= 3 && p[0] == 4 && p[1] == 9 && p[2] in 90..99) p[2] *= 10
            return p
        }
        val a = parts(first); val b = parts(second)
        for (i in 0..2) { val c = a.getOrElse(i) { 0 }.compareTo(b.getOrElse(i) { 0 }); if (c != 0) return c }
        if (first.contains('-') != second.contains('-')) return if (first.contains('-')) -1 else 1
        for (i in 3 until maxOf(a.size,b.size)) { val c = a.getOrElse(i) { 0 }.compareTo(b.getOrElse(i) { 0 }); if (c != 0) return c }
        return 0
    }
    fun selectApk(names: List<String>, abi: String, television: Boolean): String? {
        val edition = names.filter { it.endsWith(".apk",true) && it.contains("-tv-",true) == television }
        return edition.firstOrNull { it.endsWith("-$abi.apk",true) }
            ?: edition.firstOrNull { it.endsWith("-universal.apk",true) }
    }
}
