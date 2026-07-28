package ir.dicode.ping.core

internal object ExternalCoreCommandBuilder {
    fun registration(binary: String, config: String): List<String> = listOf(
        binary,
        "-c", config,
        "register", "--accept-tos", "--name", "dicodePing-Android",
    )

    fun runtime(
        coreId: String,
        binary: String,
        config: String,
        socksPort: Int,
        http2Fallback: Boolean,
    ): List<String> = when (coreId) {
        "aether" -> buildList {
            add(binary)
            addAll(listOf("--config", config, "--bind", "127.0.0.1:$socksPort", "--masque", "-4"))
            if (http2Fallback) addAll(listOf("--h2", "--fragment"))
            addAll(listOf("--scan", "balanced", "--quick-reconnect", "--noize", "firewall"))
        }
        "warp" -> buildList {
            addAll(
                listOf(
                    binary,
                    "-c", config,
                    "socks", "-b", "127.0.0.1", "-p", socksPort.toString(),
                    "--always-reconnect", "--reconnect-delay", "1s",
                )
            )
            if (http2Fallback) add("--http2")
        }
        else -> error("Unsupported external core: $coreId")
    }
}
