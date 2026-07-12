package ir.dicode.ping.xray

import android.content.Context
import android.util.Base64
import java.lang.reflect.Proxy
import java.security.SecureRandom

class CoreBridge(private val context: Context, private val status: (String) -> Unit = {}) {
    private var controller: Any? = null

    fun available(): Boolean = runCatching { Class.forName("libv2ray.Libv2ray") }.isSuccess

    fun version(): String = runCatching {
        Class.forName("libv2ray.Libv2ray")
            .getMethod("checkVersionX")
            .invoke(null)
            ?.toString()
            .orEmpty()
    }.getOrDefault("Core unavailable")

    fun start(config: String, tunFd: Int) {
        val lib = prepareEnvironment()
        val callbackClass = Class.forName("libv2ray.CoreCallbackHandler")
        val callback = Proxy.newProxyInstance(callbackClass.classLoader, arrayOf(callbackClass)) { _, method, args ->
            when (method.name.lowercase()) {
                "startup" -> {
                    status("started")
                    0L
                }
                "shutdown" -> {
                    status("stopped")
                    0L
                }
                "onemitstatus" -> {
                    status(args?.getOrNull(1)?.toString().orEmpty())
                    0L
                }
                else -> 0L
            }
        }

        controller = lib.getMethod("newCoreController", callbackClass).invoke(null, callback)
        val activeController = controller ?: error("Unable to create Xray controller")
        val start = activeController.javaClass.methods.first {
            it.name.equals("startLoop", true) && it.parameterCount == 2
        }
        start.invoke(activeController, config, tunFd)
        if (!isRunning()) error("Xray core did not enter the running state")
    }

    private fun prepareEnvironment(): Class<*> = synchronized(ENV_LOCK) {
        val lib = Class.forName("libv2ray.Libv2ray")
        runCatching {
            Class.forName("go.Seq")
                .getMethod("setContext", Context::class.java)
                .invoke(null, context.applicationContext)
        }

        val assets = context.filesDir.resolve("xray_assets").apply { mkdirs() }
        lib.getMethod("initCoreEnv", String::class.java, String::class.java)
            .invoke(null, assets.absolutePath, loadOrCreateXudpBaseKey())
        lib
    }

    /**
     * AndroidLibXrayLite forwards this value to xray.xudp.basekey. Xray expects a
     * URL-safe Base64 value that decodes to exactly 32 bytes.
     */
    private fun loadOrCreateXudpBaseKey(): String {
        val prefs = context.getSharedPreferences(CORE_PREFS, Context.MODE_PRIVATE)
        prefs.getString(KEY_XUDP_BASE_KEY, null)?.let { saved ->
            if (isValidXudpBaseKey(saved)) return saved
        }

        val bytes = ByteArray(32).also { SecureRandom().nextBytes(it) }
        val encoded = Base64.encodeToString(
            bytes,
            Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING,
        )
        check(isValidXudpBaseKey(encoded)) { "Failed to generate a valid XUDP base key" }
        prefs.edit().putString(KEY_XUDP_BASE_KEY, encoded).apply()
        return encoded
    }

    private fun isValidXudpBaseKey(value: String): Boolean = runCatching {
        Base64.decode(value, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING).size == 32
    }.getOrDefault(false)

    fun isRunning(): Boolean {
        val c = controller ?: return false
        return runCatching {
            val getter = c.javaClass.methods.firstOrNull {
                it.parameterCount == 0 &&
                    (it.name.equals("getIsRunning", true) || it.name.equals("isRunning", true))
            }
            when (val value = getter?.invoke(c)) {
                is Boolean -> value
                is Number -> value.toInt() != 0
                else -> true
            }
        }.getOrDefault(false)
    }

    fun queryTrafficDelta(): Pair<Long, Long> {
        val c = controller ?: return 0L to 0L
        return runCatching {
            val all = c.javaClass.methods.firstOrNull {
                it.name.equals("queryAllOutboundTrafficStats", true) && it.parameterCount == 0
            }
            if (all != null) {
                var upload = 0L
                var download = 0L
                all.invoke(c)?.toString().orEmpty().split(';').forEach { row ->
                    val parts = row.split(',', limit = 3)
                    if (parts.size != 3) return@forEach
                    val value = parts[2].toLongOrNull() ?: return@forEach
                    when (parts[1].lowercase()) {
                        "uplink" -> upload += value
                        "downlink" -> download += value
                    }
                }
                upload.coerceAtLeast(0L) to download.coerceAtLeast(0L)
            } else {
                val query = c.javaClass.methods.firstOrNull {
                    it.name.equals("queryStats", true) && it.parameterCount == 2
                } ?: return@runCatching 0L to 0L
                val upload = (query.invoke(c, "proxy", "uplink") as? Number)?.toLong() ?: 0L
                val download = (query.invoke(c, "proxy", "downlink") as? Number)?.toLong() ?: 0L
                upload.coerceAtLeast(0L) to download.coerceAtLeast(0L)
            }
        }.getOrDefault(0L to 0L)
    }

    /** Measures an HTTP round trip through the running Xray outbound. */
    fun measureDelay(urls: List<String> = PROBE_URLS): Long? {
        val c = controller ?: return null
        val method = c.javaClass.methods.firstOrNull {
            it.name.equals("measureDelay", true) && it.parameterCount == 1
        } ?: return null

        for (url in urls) {
            val delay = runCatching {
                (method.invoke(c, url) as? Number)?.toLong()
            }.getOrNull()
            if (delay != null && delay >= 0) return delay
        }
        return null
    }

    fun stop() {
        val c = controller ?: return
        runCatching {
            c.javaClass.methods.first { it.name.equals("stopLoop", true) }.invoke(c)
        }
        controller = null
    }

    /**
     * Builds a temporary Xray instance and performs the HTTP probe through the
     * supplied server configuration. This is a proxy health test, not ICMP/TCP
     * latency to the server host.
     */
    fun measureOutboundDelay(config: String, urls: List<String> = OUTBOUND_PROBE_URLS): Long {
        val lib = runCatching { prepareEnvironment() }.getOrNull() ?: return -1L
        val method = runCatching {
            lib.getMethod("measureOutboundDelay", String::class.java, String::class.java)
        }.getOrNull() ?: return -1L

        for (url in urls) {
            val delay = runCatching {
                (method.invoke(null, config, url) as? Number)?.toLong() ?: -1L
            }.getOrDefault(-1L)
            if (delay >= 0) return delay
        }
        return -1L
    }

    private companion object {
        val ENV_LOCK = Any()
        val PROBE_URLS = listOf(
            "https://www.gstatic.com/generate_204",
            "https://cp.cloudflare.com/generate_204",
        )
        val OUTBOUND_PROBE_URLS = listOf(PROBE_URLS.first())
        const val CORE_PREFS = "dicodeping_core"
        const val KEY_XUDP_BASE_KEY = "xudp_base_key_v1"
    }
}
