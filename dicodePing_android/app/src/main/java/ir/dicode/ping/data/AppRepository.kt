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
import java.net.InetSocketAddress
import java.net.Socket
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
        settings.saveServers(servers.value)
        if (servers.value.isNotEmpty() && settings.lastServerRefreshAt <= 0L) {
            settings.lastServerRefreshAt = System.currentTimeMillis()
        }
    }

    /**
     * Prepares a trustworthy automatic target before leaving the splash screen.
     * First launch and the two-day refresh both download, perform a real Xray HTTP
     * probe, and resolve location for a bounded candidate set. Remaining servers
     * continue in the background after at least one usable choice is ready.
     */
    suspend fun initialize() = withContext(Dispatchers.IO) {
        refreshMutex.withLock {
            val refreshDue = settings.isServerRefreshDue()
            if (refreshDue) {
                AppLog.i("Repository", "Startup server refresh is due")
                refreshServersInternal()
            } else {
                AppLog.i("Repository", "Startup cache is fresh")
            }

            val snapshot = servers.value
            if (snapshot.isEmpty()) return@withLock
            if (refreshDue || snapshot.none(::isAutoEligible)) {
                val startup = rankStartupCandidates(snapshot)
                pingAndLocate(startup, mergeWithExisting = true)
                val tested = startup.asSequence().map { it.id }.toHashSet()
                val remaining = servers.value.filterNot { it.id in tested }
                if (remaining.isNotEmpty()) {
                    scope.launch {
                        refreshMutex.withLock {
                            pingAndLocate(remaining, mergeWithExisting = true)
                        }
                    }
                }
            }
        }
    }

    fun refreshAll() {
        if (progress.value.active) return
        AppLog.i("Repository", "Manual server refresh requested")
        scope.launch {
            refreshMutex.withLock {
                refreshServersInternal()
                val snapshot = servers.value
                if (snapshot.isEmpty()) return@withLock
                val startup = rankStartupCandidates(snapshot)
                pingAndLocate(startup, mergeWithExisting = true)
                val tested = startup.asSequence().map { it.id }.toHashSet()
                val remaining = servers.value.filterNot { it.id in tested }
                if (remaining.isNotEmpty()) pingAndLocate(remaining, mergeWithExisting = true)
            }
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

    private suspend fun rankStartupCandidates(input: List<ServerRecord>): List<ServerRecord> = coroutineScope {
        if (input.size <= STARTUP_REAL_PROBE_LIMIT) return@coroutineScope input
        val sem = Semaphore(STARTUP_PREFILTER_CONCURRENCY)
        input.map { server ->
            async(Dispatchers.IO) {
                sem.withPermit {
                    val previous = server.pingMs.takeIf { isAutoEligible(server) }
                    if (previous != null) return@withPermit server to previous
                    val started = System.nanoTime()
                    val reachable = runCatching {
                        Socket().use { socket ->
                            socket.connect(
                                InetSocketAddress(server.host, server.port),
                                STARTUP_CONNECT_TIMEOUT_MS,
                            )
                        }
                        true
                    }.getOrDefault(false)
                    val elapsed = ((System.nanoTime() - started) / 1_000_000L)
                        .coerceAtMost(Int.MAX_VALUE.toLong())
                        .toInt()
                    server to if (reachable) elapsed else Int.MAX_VALUE
                }
            }
        }.awaitAll()
            .sortedWith(compareBy<Pair<ServerRecord, Int>> { it.second }.thenBy { it.first.sourceName })
            .take(STARTUP_REAL_PROBE_LIMIT)
            .map { it.first }
    }

    fun pingAll() {
        if (!progress.value.active) {
            AppLog.i("Repository", "Real server test requested for ${servers.value.size} servers")
            scope.launch { refreshMutex.withLock { pingAndLocate(servers.value, mergeWithExisting = true) } }
        }
    }

    private suspend fun pingAndLocate(
        input: List<ServerRecord>,
        mergeWithExisting: Boolean = false,
    ) = coroutineScope {
        val total = input.size
        if (total == 0) {
            progress.value = ProgressState()
            return@coroutineScope
        }

        try {
            val done = AtomicInteger(0)
            val sem = Semaphore(4)
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

            applyServerUpdates(pinged, mergeWithExisting)

            val byIp = pinged
                .filter { it.healthy && it.ip.isNotBlank() }
                .map { it.ip }
                .distinct()
            val geoDone = AtomicInteger(0)
            val geoSem = Semaphore(6)
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
            applyServerUpdates(located, mergeWithExisting)
        } finally {
            progress.value = ProgressState()
        }
    }

    private fun applyServerUpdates(updated: List<ServerRecord>, mergeWithExisting: Boolean) {
        val next = if (mergeWithExisting) {
            val byId = updated.associateBy { it.id }
            servers.value.map { current -> byId[current.id] ?: current }
        } else {
            updated
        }
        servers.value = sortServers(next)
        settings.saveServers(servers.value)
    }

    private fun isAutoEligible(server: ServerRecord): Boolean =
        server.healthy &&
            server.pingKind == REAL_PROXY_PING &&
            server.pingMs != null &&
            server.countryCode.isNotBlank()

    private fun sortServers(rows: List<ServerRecord>) = rows.sortedWith(
        compareByDescending<ServerRecord> { it.favorite }
            .thenByDescending(::isAutoEligible)
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
        servers.value.filter(::isAutoEligible).minByOrNull { it.pingMs!! }

    fun connectionTarget(): ServerRecord? = if (connectionMode.value == "manual") {
        selectedServer()
    } else {
        bestServer()
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
        private const val STARTUP_REAL_PROBE_LIMIT = 18
        private const val STARTUP_PREFILTER_CONCURRENCY = 24
        private const val STARTUP_CONNECT_TIMEOUT_MS = 900

        @Volatile
        private var instance: AppRepository? = null

        fun get(context: Context) = instance ?: synchronized(this) {
            instance ?: AppRepository(context).also { instance = it }
        }
    }
}
