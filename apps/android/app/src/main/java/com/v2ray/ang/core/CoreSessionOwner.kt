package com.v2ray.ang.core

/** Serial lifecycle tasks can outlive their Android service instance. Identity is session authority. */
internal class CoreSessionOwner<T : Any> {
    @Volatile private var owner: T? = null
    fun claim(value: T) { owner = value }
    fun owns(value: T): Boolean = owner === value
    @Synchronized fun release(value: T): Boolean {
        if (!owns(value)) return false
        owner = null
        return true
    }
}
