package ir.dicode.ping.data

import android.content.Context
import ir.dicode.ping.net.ConfigParser
import ir.dicode.ping.net.GeoResolver
import ir.dicode.ping.net.SubscriptionClient
import ir.dicode.ping.util.AppLog
import ir.dicode.ping.xray.CoreBridge
import ir.dicode.ping.xray.XrayConfigBuilder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import java.net.InetAddress
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicInteger

class AppRepository private constructor(context: Context) {
    private val app = context.applicationContext
    val settings = SettingsStore(app)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val downloader = SubscriptionClient()
    private val geo = GeoResolver()
    private val proxyProbe = CoreBridge(app)
    private val refreshMutex = Mutex()

    val sources = MutableStateFlow(settings.loadSources().toList())
    val servers = MutableStateFlow(
        settings.loadServers().map { server ->
            if (server.pingKind == REAL_PROXY_PING) server else server.copy(
                pingMs = null,
                pingKind = "",
                healthy = false,
            )
        }
    )
    val progress = MutableStateFlow(ProgressState())
    val error = MutableStateFlow<String?>(null)
    val selectedServerId = MutableStateFlow(settings.selectedServerId)
    val connectionMode = MutableStateFlow(settings.connectionMode)

    init {
        // Persist the removal of legacy host-only ICMP/TCP values such as false 1 ms results.
        settings.saveServers(servers.value)
        // Existing installations did not store a refresh timestamp. Treat their current
        // cache as fresh instead of forcing a network request on every migration launch.
        if (servers.value.isNotEmpty() && settings.lastServerRefreshAt <= 0L) {
            settings.lastServerRefreshAt = System.currentTimeMillis()
        }
    }

    /**
     * Performs the lightweight startup preparation. The subscription is fetched only
     * when the cache is empty or older than two days. Health tests are deliberately
     * not run at startup because each test creates a temporary Xray instance and costs
     * network, CPU and battery. Users can request a real test from the servers screen.
     */
    suspend fun initialize() = withContext(Dispatchers.IO) {
        if (!settings.isServerRefreshDue()) {
            AppLog.i("Repository", "Startup cache is fresh; skipping server refresh")
            return@withContext
        }
        AppLog.i("Repository", "Startup server refresh is due")
        refreshMutex.withLock {
            if (settings.isServerRefreshDue()) refreshServersInternal()
        }
    }

    fun refreshAll() {
        if (progress.value.active) return
        AppLog.i("Repository", "Manual server refresh requested")
        scope.launch {
            refreshMutex.withLock { refreshServersInternal() }
        }
    }

    private suspend fun refreshServersInternal() {
        if (progress.value.active) return
        error.value = null
        val enabled = sources.value.filter { it.enabled }.sortedBy { it.order }
        val discovered = mutableListOf<ServerRecord>()
        var successfulSources = 0

        enabled.forEachIndexed { sourceIndex, source ->
            progress.value = ProgressState(true, "download", sourceIndex, enabled.size, source.name)
            runCatching {
                val text = downloader.download(source.url) { read, total ->
                    val local = if (total > 0) ((read * 100) / total).toInt() else 0
                    progress.value = ProgressState(
                        true,
                        "download",
                        sourceIndex * 100 + local,
                        enabled.size * 100,
                        source.name,
                    )
                }
                ConfigParser.decodeSubscription(text).forEach { raw ->
                    ConfigParser.parse(raw)?.let { parsed ->
                        discovered += ServerRecord(
                            id = idForRaw(raw),
                            raw = raw,
                            name = parsed.name,
                            protocol = parsed.protocol.uppercase(),
                            host = parsed.host,
                            port = parsed.port,
                            sourceId = source.id,
                            sourceName = source.name,
                        )
                    }
                }
                successfulSources++
            }.onFailure {
                AppLog.w("Repository", "Source failed: ${source.name}", it)
                error.value = "${source.name}: ${it.message}"
            }
        }

        if (discovered.isNotEmpty()) {
            AppLog.i("Repository", "Downloaded ${discovered.size} server candidates")
            val old = servers.value.associateBy { it.id }
            val unique = discovered.distinctBy { it.id }.map { fresh ->
                old[fresh.id]?.let { previous ->
                    val hasRealProbe = previous.pingKind == REAL_PROXY_PING
                    fresh.copy(
                        pingMs = previous.pingMs.takeIf { hasRealProbe },
                        pingKind = previous.pingKind.takeIf { hasRealProbe }.orEmpty(),
                        ip = previous.ip,
                        country = previous.country,
                        countryCode = previous.countryCode,
                        region = previous.region,
                        city = previous.city,
                        isp = previous.isp,
                        asn = previous.asn,
                        geoConfidence = previous.geoConfidence,
                        healthy = hasRealProbe && previous.healthy,
                        favorite = previous.favorite,
                    )
                } ?: fresh
            }
            servers.value = sortServers(unique)
            settings.saveServers(servers.value)
            if (successfulSources > 0) settings.lastServerRefreshAt = System.currentTimeMillis()
        } else if (servers.value.isEmpty()) {
            error.value = error.value ?: "No servers were received"
        }
        progress.value = ProgressState()
    }

    fun pingAll() {
        if (!progress.value.active) {
            AppLog.i("Repository", "Real server test requested for ${servers.value.size} servers")
            scope.launch { pingAndLocate(servers.value) }
        }
    }

    /**
     * Tests each server by creating a temporary Xray instance and completing an HTTP
     * request through that outbound. This intentionally replaces ICMP/TCP-to-host
     * timing, which can report 1 ms even when the proxy credentials are unusable.
     */
    private suspend fun pingAndLocate(input: List<ServerRecord>) = coroutineScope {
        val total = input.size
        if (total == 0) {
            progress.value = ProgressState()
            return@coroutineScope
        }

        val done = AtomicInteger(0)
        val sem = Semaphore(3)
        val pinged = input.map { server ->
            async(Dispatchers.IO) {
                sem.withPermit {
                    val ip = runCatching {
                        InetAddress.getByName(server.host).hostAddress.orEmpty()
                    }.getOrDefault("")
                    val delay = runCatching {
                        proxyProbe.measureOutboundDelay(XrayConfigBuilder.build(server.raw))
                    }.getOrDefault(-1L)

                    val pingMs = delay
                        .takeIf { it in 1..60_000 }
                        ?.coerceAtMost(Int.MAX_VALUE.toLong())
                        ?.toInt()
                    progress.value = ProgressState(
                        true,
                        "ping",
                        done.incrementAndGet(),
                        total,
                        server.name,
                    )
                    server.copy(
                        ip = ip,
                        pingMs = pingMs,
                        pingKind = if (pingMs != null) REAL_PROXY_PING else "",
                        healthy = pingMs != null,
                    )
                }
            }
        }.awaitAll()

        servers.value = sortServers(pinged)
        settings.saveServers(servers.value)

        val byIp = pinged.filter { it.ip.isNotBlank() }.map { it.ip }.distinct()
        val geoDone = AtomicInteger(0)
        val geoSem = Semaphore(5)
        val geoByIp = byIp.map { ip ->
            async(Dispatchers.IO) {
                geoSem.withPermit {
                    val result = geo.resolve(ip)
                    progress.value = ProgressState(
                        true,
                        "geo",
                        geoDone.incrementAndGet(),
                        byIp.size,
                        ip,
                    )
                    ip to result
                }
            }
        }.awaitAll().toMap()

        val located = pinged.map { server ->
            geoByIp[server.ip]?.let { g ->
                server.copy(
                    country = g.country,
                    countryCode = g.countryCode,
                    region = g.region,
                    city = g.city,
                    isp = g.isp,
                    asn = g.asn,
                    geoConfidence = g.confidence,
                )
            } ?: server
        }
        servers.value = sortServers(located)
        settings.saveServers(servers.value)
        progress.value = ProgressState()
    }

    private fun sortServers(rows: List<ServerRecord>) = rows.sortedWith(
        compareByDescending<ServerRecord> { it.favorite }
            .thenByDescending { it.healthy }
            .thenBy { it.pingMs ?: Int.MAX_VALUE }
    )

    fun saveSources(list: List<SourceDefinition>) {
        val normalized = list.sortedBy { it.order }.mapIndexed { index, source ->
            source.apply { order = index }
        }
        sources.value = normalized
        settings.saveSources(normalized)
    }

    fun addSource(name: String, url: String) {
        if (!url.startsWith("https://") || sources.value.any { it.url.equals(url, true) }) return
        saveSources(
            sources.value + SourceDefinition(
                SettingsStore.idForUrl(url),
                name,
                url,
                sources.value.size,
            )
        )
    }

    fun updateSource(updated: SourceDefinition) =
        saveSources(sources.value.map { if (it.id == updated.id) updated else it })

    fun removeSource(id: String) =
        saveSources(sources.value.filterNot { it.id == id && !it.isDefault })

    fun moveSource(id: String, delta: Int) {
        val list = sources.value.toMutableList()
        val index = list.indexOfFirst { it.id == id }
        if (index < 0) return
        val target = (index + delta).coerceIn(0, list.lastIndex)
        if (index != target) {
            val item = list.removeAt(index)
            list.add(target, item)
            saveSources(list)
        }
    }

    fun setConnectionMode(mode: String) {
        val normalized = if (mode == "manual") "manual" else "auto"
        settings.connectionMode = normalized
        connectionMode.value = normalized
    }

    fun selectServer(id: String, userInitiated: Boolean = true) {
        settings.selectedServerId = id
        selectedServerId.value = id
        if (userInitiated) setConnectionMode("manual")
    }

    fun serverById(id: String): ServerRecord? =
        servers.value.firstOrNull { it.id == id }

    fun selectedServer(): ServerRecord? =
        serverById(selectedServerId.value)

    fun bestServer(): ServerRecord? =
        servers.value.filter { it.healthy && it.pingMs != null }.minByOrNull { it.pingMs!! }

    /** The exact server shown on Home and used by the next connect action. */
    fun connectionTarget(): ServerRecord? = if (connectionMode.value == "manual") {
        selectedServer()
    } else {
        bestServer() ?: selectedServer() ?: servers.value.firstOrNull()
    }

    fun setFavorite(id: String) {
        servers.value = servers.value.map {
            if (it.id == id) it.copy(favorite = !it.favorite) else it
        }
        settings.saveServers(servers.value)
    }

    private fun idForRaw(raw: String): String = MessageDigest.getInstance("SHA-256")
        .digest(raw.substringBefore('#').toByteArray())
        .take(8)
        .joinToString("") { "%02x".format(it) }

    companion object {
        private const val REAL_PROXY_PING = "PROXY_HTTP"

        @Volatile
        private var instance: AppRepository? = null

        fun get(context: Context) = instance ?: synchronized(this) {
            instance ?: AppRepository(context).also { instance = it }
        }
    }
}
