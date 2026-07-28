package ir.dicode.ping.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SubscriptionClientUrlTest {
    @Test
    fun blankAndUnsupportedSchemesAreRejectedWithoutThrowing() {
        assertNull(normalizedSubscriptionHttpUrl(""))
        assertNull(normalizedSubscriptionHttpUrl("   \n"))
        assertNull(normalizedSubscriptionHttpUrl("file:///tmp/sub.txt"))
        assertNull(normalizedSubscriptionHttpUrl("ftp://example.com/sub"))
    }

    @Test
    fun missingSchemeIsSafelyUpgradedToHttps() {
        assertEquals(
            "https://raw.githubusercontent.com/owner/repo/main/sub.txt",
            normalizedSubscriptionHttpUrl(" raw.githubusercontent.com/owner/repo/main/sub.txt ")?.toString(),
        )
    }

    @Test
    fun validHttpAndHttpsUrlsArePreserved() {
        assertEquals(
            "https://example.com/sub",
            normalizedSubscriptionHttpUrl("https://example.com/sub")?.toString(),
        )
        assertEquals(
            "http://127.0.0.1:8080/sub",
            normalizedSubscriptionHttpUrl("http://127.0.0.1:8080/sub")?.toString(),
        )
    }
}
