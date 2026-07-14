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
    private val liveUpdateMutex = Mutex()

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

    /** First launch is prepared on the splash; cached lists open immediately. */
    suspend fun initialize() = withContext(Dispatchers.IO) {
        refreshMutex.withLock {
            // A timed refresh used to perform download, geolocation and every
            // probe before MainActivity could be shown.  It made opening the app
            // look frozen and also hid the user's cached server list.
            if (servers.value.isEmpty()) {
                AppLog.i("Repository", "First launch: preparing initial servers")
                refreshServersInternal()
                val startup = rankStartupCandidates(servers.value)
                locateServers(startup, mergeWithExisting = true)
                pingServers(startup)
                val tested = startup.asSequence().map { it.id }.toHashSet()
                val remaining = servers.value.filterNot { it.id in tested }
                if (remaining.isNotEmpty()) {
                    scope.launch {
                        refreshMutex.withLock { locateServers(remaining, mergeWithExisting = true); pingServers(remaining) }
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
                // Manual refresh is intentionally one visible, deterministic pipeline:
                // download -> location -> bounded concurrent real proxy tests.
                locateServers(snapshot, mergeWithExisting = true)
                pingServers(servers.value)
                rememberSourceRevisions()
            }
        }
    }

    /** Returns changed source names.  The initial check establishes a baseline. */
    suspend fun subscriptionUpdates(): List<SourceDefinition> = withContext(Dispatchers.IO) {
        val previous = settings.sourceRevisions
        val observed = mutableMapOf<String, String>()
        val changed = sources.value.filter { it.enabled }.filter { source ->
            val revision = downloader.revision(source.url)
            if (revision.isBlank()) false else {
                observed[source.id] = revision
                previous[source.id]?.let { it != revision } ?: false
            }
        }
        if (previous.isEmpty() && observed.isNotEmpty()) settings.sourceRevisions = observed
        changed
    }

    private suspend fun rememberSourceRevisions() {
        val observed = sources.value.filter { it.enabled }.mapNotNull { source ->
            downloader.revision(source.url).takeIf { it.isNotBlank() }?.let { source.id to it }
        }.toMap()
        if (observed.isNotEmpty()) settings.sourceRevisions = observed
    }

    private suspend fun refreshServersInternal() {
        if (progress.value.active) return
        error.value = null
        val enabled = sources.value.filter { it.enabled }.sortedBy { it.order }
        val discovered = mutableListOf<ServerRecord>()
        var successfulSources = 0

        progress.value = ProgressState(true, "download", 0, enabled.size, "Downloading servers")
        val completed = AtomicInteger(0)
        val downloadSem = Semaphore(DOWNLOAD_CONCURRENCY)
        val sourceResults = coroutineScope {
            enabled.mapIndexed { sourceIndex, source ->
                async(Dispatchers.IO) {
                    downloadSem.withPermit {
                        val downloadResult = runCatching {
                            val text = downloader.download(source.url) { _, _ -> Unit }
                            ConfigParser.decodeSubscription(text).mapNotNull { raw ->
                                ConfigParser.parse(raw)?.let { parsed ->
                                    ServerRecord(
                                        id = idForRaw(raw), raw = raw, name = parsed.name,
                                        protocol = parsed.protocol.uppercase(), host = parsed.host,
                                        port = parsed.port, sourceId = source.id, sourceName = source.name,
                                    )
                                }
                            }
                        }.onFailure {
                            AppLog.w("Repository", "Source failed: ${source.name}", it)
                            error.value = "${source.name}: ${it.message}"
                        }
                        val rows = downloadResult.getOrDefault(emptyList())
                        val done = completed.incrementAndGet()
                        progress.value = ProgressState(true, "download", done, enabled.size, source.name)
                        Triple(sourceIndex, rows, downloadResult.isSuccess)
                    }
                }
            }.awaitAll()
        }.sortedBy { it.first }
        sourceResults.forEach { (_, rows, success) ->
            discovered += rows
            if (success) successfulSources++
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
            // Keep source order stable until the final ping stage. This prevents rows from
            // jumping while location and latency results arrive.
            servers.value = unique
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
            scope.launch {
                refreshMutex.withLock {
                    val missingLocation = servers.value.filter { it.ip.isBlank() || it.countryCode.isBlank() }
                    if (missingLocation.isNotEmpty()) locateServers(missingLocation, mergeWithExisting = true)
                    pingServers(servers.value)
                }
            }
        }
    }

    private suspend fun locateServers(
        input: List<ServerRecord>,
        mergeWithExisting: Boolean = false,
    ) = coroutineScope {
        val total = input.size
        if (total == 0) {
            progress.value = ProgressState()
            return@coroutineScope
        }

        try {
            progress.value = ProgressState(true, "geo", 0, total, "Resolving server locations")
            val dnsDone = AtomicInteger(0)
            val dnsSem = Semaphore(DNS_CONCURRENCY)
            val resolved = input.map { server ->
                async(Dispatchers.IO) {
                    dnsSem.withPermit {
                        val ip = runCatching {
                            InetAddress.getByName(server.host).hostAddress.orEmpty()
                        }.getOrDefault("")
                        progress.value = ProgressState(
                            true, "geo", dnsDone.incrementAndGet(), total, server.name,
                        )
                        server.copy(ip = ip)
                    }
                }
            }.awaitAll()
            applyServerUpdates(resolved, mergeWithExisting, sort = false)

            val byIp = resolved.filter { it.ip.isNotBlank() }.map { it.ip }.distinct()
            val geoDone = AtomicInteger(0)
            val geoSem = Semaphore(GEO_CONCURRENCY)
            val geoByIp = byIp.map { ip ->
                async(Dispatchers.IO) {
                    geoSem.withPermit {
                        val result = geo.resolve(ip)
                        progress.value = ProgressState(
                            true,
                            "geo",
                            geoDone.incrementAndGet(),
                            byIp.size.coerceAtLeast(1),
                            ip,
                        )
                        ip to result
                    }
                }
            }.awaitAll().toMap()

            val located = resolved.map { server ->
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
            applyServerUpdates(located, mergeWithExisting, sort = false)
        } finally {
            progress.value = ProgressState()
        }
    }

    private suspend fun pingServers(input: List<ServerRecord>) = coroutineScope {
        if (input.isEmpty()) return@coroutineScope
        val inputIds = input.mapTo(HashSet()) { it.id }
        // Emit testing state without reordering. Existing rows remain visible and selected.
        liveUpdateMutex.withLock {
            servers.value = servers.value.map { current ->
                if (current.id in inputIds) current.copy(
                    pingMs = null, pingKind = "", healthy = false,
                    testState = ServerRecord.TEST_RUNNING,
                ) else current
            }
        }

        try {
            val done = AtomicInteger(0)
            progress.value = ProgressState(true, "ping", 0, input.size, "Testing servers")

            suspend fun runBatch(
                batch: List<ServerRecord>,
                concurrency: Int,
                countProgress: Boolean,
            ): List<ServerRecord> = coroutineScope {
                val sem = Semaphore(concurrency)
                batch.map { server ->
                    async(Dispatchers.IO) {
                        sem.withPermit {
                        val delay = runCatching {
                            proxyProbe.measureOutboundDelay(XrayConfigBuilder.build(server.raw))
                        }.getOrDefault(-1L)
                        val pingMs = delay.takeIf { it in 1..60_000 }
                            ?.coerceAtMost(Int.MAX_VALUE.toLong())?.toInt()
                        val updated = server.copy(
                            pingMs = pingMs,
                            pingKind = if (pingMs != null) REAL_PROXY_PING else "",
                            healthy = pingMs != null,
                            testState = if (pingMs != null) ServerRecord.TEST_IDLE else ServerRecord.TEST_FAILED,
                        )
                            if (countProgress) {
                                progress.value = ProgressState(
                                    true, "ping", done.incrementAndGet(), input.size, server.name,
                                )
                            }
                            updated
                        }
                    }
                }.awaitAll()
            }

            val firstPass = mutableListOf<ServerRecord>()
            input.chunked(REAL_PROBE_PAGE_SIZE).forEach { page ->
                val results = runBatch(page, REAL_PROBE_CONCURRENCY, countProgress = true)
                firstPass += results
                // One list emission per page keeps RecyclerView smooth while
                // preserving the visible order and current selection.
                liveUpdateMutex.withLock { applyServerUpdates(results, true, sort = false, persist = false) }
            }
            val failed = firstPass.filterNot { it.healthy }
            if (failed.isNotEmpty()) {
                val failedIds = failed.mapTo(HashSet()) { it.id }
                liveUpdateMutex.withLock {
                    servers.value = servers.value.map { current ->
                        if (current.id in failedIds) current.copy(testState = ServerRecord.TEST_RUNNING) else current
                    }
                }
                failed.chunked(RETRY_PROBE_PAGE_SIZE).forEach { page ->
                    val results = runBatch(page, RETRY_PROBE_CONCURRENCY, countProgress = false)
                    liveUpdateMutex.withLock { applyServerUpdates(results, true, sort = false, persist = false) }
                }
            }
            liveUpdateMutex.withLock {
                servers.value = sortServers(servers.value)
                settings.saveServers(servers.value)
            }
        } finally {
            liveUpdateMutex.withLock {
                servers.value = servers.value.map { current ->
                    if (current.testState == ServerRecord.TEST_RUNNING) {
                        current.copy(testState = ServerRecord.TEST_FAILED)
                    } else {
                        current
                    }
                }
            }
            progress.value = ProgressState()
        }
    }

    private fun applyServerUpdates(
        updated: List<ServerRecord>,
        mergeWithExisting: Boolean,
        sort: Boolean = true,
        persist: Boolean = true,
    ) {
        val next = if (mergeWithExisting) {
            val byId = updated.associateBy { it.id }
            servers.value.map { current -> byId[current.id]?.let { incoming ->
                incoming.copy(
                    ip = incoming.ip.ifBlank { current.ip },
                    country = incoming.country.ifBlank { current.country },
                    countryCode = incoming.countryCode.ifBlank { current.countryCode },
                    region = incoming.region.ifBlank { current.region },
                    city = incoming.city.ifBlank { current.city },
                    isp = incoming.isp.ifBlank { current.isp },
                    asn = incoming.asn.ifBlank { current.asn },
                    geoConfidence = incoming.geoConfidence.ifBlank { current.geoConfidence },
                    favorite = current.favorite,
                )
            } ?: current }
        } else {
            updated
        }
        servers.value = if (sort) sortServers(next) else next
        if (persist) settings.saveServers(servers.value)
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
        private const val DOWNLOAD_CONCURRENCY = 4
        private const val DNS_CONCURRENCY = 32
        private const val GEO_CONCURRENCY = 8
        private const val REAL_PROBE_CONCURRENCY = 12
        private const val REAL_PROBE_PAGE_SIZE = 36
        private const val RETRY_PROBE_CONCURRENCY = 6
        private const val RETRY_PROBE_PAGE_SIZE = 12

        @Volatile
        private var instance: AppRepository? = null

        fun get(context: Context) = instance ?: synchronized(this) {
            instance ?: AppRepository(context).also { instance = it }
        }
    }
}
