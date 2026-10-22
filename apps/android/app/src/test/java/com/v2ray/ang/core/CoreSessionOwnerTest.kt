package com.v2ray.ang.core

import org.junit.jupiter.api.Assertions.*
import org.junit.jupiter.api.Test

class CoreSessionOwnerTest {
    @Test fun delayedOldDestroyCannotStopANewServiceAndDuplicateTeardownIsIgnored() {
        val owner = CoreSessionOwner<Any>()
        val old = Any(); val next = Any()
        owner.claim(old)
        assertTrue(owner.release(old))
        owner.claim(next)
        assertFalse(owner.release(old))
        assertTrue(owner.owns(next))
        assertTrue(owner.release(next))
        assertFalse(owner.release(next))
    }
}
