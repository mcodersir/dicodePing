package com.v2ray.ang.core

/** The backing store is shared by the UI and daemon; no process-local counter can substitute for it. */
internal class ConnectionRequests(private val read: () -> String, private val write: (String) -> Unit) {
    fun version(): String = read()
    fun isCurrent(version: String): Boolean = read() == version
    fun cancel() { write(java.util.UUID.randomUUID().toString()) }

    fun restart(send: (String, (Boolean) -> Unit) -> Unit, startIfStopped: () -> Unit) {
        val version = version()
        send(version) { handled -> if (!handled && isCurrent(version)) startIfStopped() }
    }
}
