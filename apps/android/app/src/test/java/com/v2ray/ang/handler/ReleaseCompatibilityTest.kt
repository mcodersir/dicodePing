package com.v2ray.ang.handler
import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test
class ReleaseCompatibilityTest {
 @Test fun stable99FollowsAll98Hotfixes() {
  for (old in listOf("4.9.92","4.9.98","4.9.981","4.9.982","4.9.983","4.9.985")) {
   assertTrue(ReleaseCompatibility.compareVersions("4.9.99",old)>0,old)
   assertTrue(ReleaseCompatibility.compareVersions(old,"4.9.99")<0,old)
  }
  assertTrue(ReleaseCompatibility.compareVersions("4.10.0","4.9.99")>0)
  assertTrue(ReleaseCompatibility.compareVersions("4.9.99","4.9.99-beta.1")>0)
 }
 @Test fun updaterKeepsPhoneAndTvPackagesSeparate() {
  val assets=listOf("DicodePing-4.9.99-tv-universal.apk","DicodePing-4.9.99-universal.apk","DicodePing-4.9.99-arm64-v8a.apk")
  assertEquals(assets[2],ReleaseCompatibility.selectApk(assets,"arm64-v8a",false))
  assertEquals(assets[0],ReleaseCompatibility.selectApk(assets,"arm64-v8a",true))
  assertEquals(assets[1],ReleaseCompatibility.selectApk(assets,"unknown",false))
  assertNull(ReleaseCompatibility.selectApk(listOf(assets[0]),"arm64-v8a",false))
 }
}
