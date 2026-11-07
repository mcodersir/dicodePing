package com.v2ray.ang.util

object FoxPersianDate {
    fun format(year: Int, month: Int, day: Int): String {
        val gregorian = java.util.GregorianCalendar(year, month - 1, day, 12, 0)
        val persian = android.icu.util.Calendar.getInstance(android.icu.util.ULocale("fa_IR@calendar=persian"))
        persian.timeInMillis = gregorian.timeInMillis
        return String.format(java.util.Locale.ROOT, "%04d/%02d/%02d", persian.get(android.icu.util.Calendar.YEAR), persian.get(android.icu.util.Calendar.MONTH) + 1, persian.get(android.icu.util.Calendar.DAY_OF_MONTH))
    }
}
