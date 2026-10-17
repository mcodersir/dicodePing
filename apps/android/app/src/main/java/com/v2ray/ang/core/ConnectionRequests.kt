package com.v2ray.ang.core

/** The backing store is shared by the UI and daemon; no process-local counter can substitute for it. */
internal class ConnectionRequests(private val read: () -> String, private val write: (String) -> Unit) {
    fun version(): String = read()
    fun isCurrent(version: String): Boolean = read() == version
    fun begin(): String = java.util.UUID.randomUUID().toString().also(write)
    fun cancel() { begin() }

    fun restart(send: (String, (Boolean) -> Unit) -> Unit, startIfStopped: () -> Unit) {
        val version = begin()
        send(version) { handled -> if (!handled && isCurrent(version)) startIfStopped() }
    }
}
