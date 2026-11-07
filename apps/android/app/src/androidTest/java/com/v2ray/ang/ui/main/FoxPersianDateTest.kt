package com.v2ray.ang.ui.main
import org.junit.Test
import org.junit.Assert.*
import androidx.test.platform.app.InstrumentationRegistry
import com.google.gson.JsonParser
import com.v2ray.ang.core.CoreConfigManager
class FoxPersianDateTest {
 @Test fun resetDateUsesPersianCalendar() { assertEquals("1405/01/01", com.v2ray.ang.util.FoxPersianDate.format(2026, 3, 21)) }
 @Test fun countryFlagsAreRealBundledImages() {
  val assets = InstrumentationRegistry.getInstrumentation().targetContext.assets
  for (code in listOf("us", "de", "jp")) assets.open("flags/$code.png").use {
   val bitmap = android.graphics.BitmapFactory.decodeStream(it)
   assertNotNull(bitmap); assertTrue(bitmap.width > 10); assertTrue(bitmap.height > 10)
  }
 }
 @Test fun fakeDnsIsRecoveredBeforeRoutingToBlockedDefault() {
  val json=JsonParser.parseString("""{"dns":{"servers":["fakedns"]},"inbounds":[{"protocol":"tun","sniffing":{"enabled":false,"routeOnly":true}},{"protocol":"socks"}]}""").asJsonObject
  CoreConfigManager.applyFakeDnsRecovery(json)
  json.getAsJsonArray("inbounds").forEach {
   val sniff=it.asJsonObject.getAsJsonObject("sniffing")
   assertTrue(sniff.get("enabled").asBoolean); assertFalse(sniff.get("routeOnly").asBoolean)
   assertTrue(sniff.getAsJsonArray("destOverride").any { it.asString=="fakedns" })
  }
 }
}
