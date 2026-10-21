package com.v2ray.ang.service

/** One process-wide queue: an old service must finish releasing ports before a new one starts. */
internal object CoreLifecycleWorker {
    val executor: java.util.concurrent.ExecutorService = java.util.concurrent.Executors.newSingleThreadExecutor { task ->
        Thread(task, "DicodeCoreLifecycle")
    }
}
