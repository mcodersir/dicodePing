package com.v2ray.ang.ui.server

import android.app.Application
import android.util.Log
import com.v2ray.ang.AppConfig
import com.v2ray.ang.R
import com.v2ray.ang.core.AetherExitNode
import com.v2ray.ang.core.AetherIdentity
import com.v2ray.ang.core.AetherIdentityManager
import com.v2ray.ang.core.AetherIdentityStatus
import com.v2ray.ang.core.AetherScanResult
import com.v2ray.ang.core.ExitNodeOutbound
import com.v2ray.ang.dto.AetherEndpoint
import com.v2ray.ang.dto.V2rayConfig
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.enums.AetherProtocol
import com.v2ray.ang.enums.EConfigType
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withContext
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertSame
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.mockito.kotlin.mock

class ServerAetherViewModelTest {

    private val profile = ProfileItem.create(EConfigType.AETHER).apply { aetherProtocol = AetherProtocol.MASQUE.type }
    private val found = AetherScanResult(AetherEndpoint("162.159.197.3", 443))
    private val oldKey = AetherIdentity("a1b2c3d4e5f6", "172.16.0.2", "2606:4700:110:8a36::1")

    private class FakeSource : AetherEditorSource {
        var available = true
        var session: AetherSession? = null
        var scanner: suspend (ProfileItem, (String) -> Unit) -> AetherScanResult? = { _, _ -> null }
        var clearer: suspend () -> Boolean = { true }
        var regions: List<String> = emptyList()
        var port = 10819
        var taken = setOf(10808, 10809, 10822)
        val identities = mutableMapOf<AetherProtocol, AetherIdentityStatus>()
        val missingFiles = mutableSetOf<String>()

        /** When set, a look at the key files waits for it, as one off the main thread takes its time. */
        var keysGate: CompletableDeferred<Unit>? = null
        var nodes: List<AetherExitNode> = emptyList()
        val found = mutableMapOf<String, ExitNodeOutbound>()

        override suspend fun isCoreAvailable() = available
        override suspend fun isPsiphonAvailable(): Boolean = false
        override suspend fun isTorTransportsAvailable(): Boolean = false
        override suspend fun activeSession() = session
        override suspend fun scan(profile: ProfileItem, onOutput: (String) -> Unit) = scanner(profile, onOutput)
        override suspend fun identityStatus(protocol: AetherProtocol) =
            identities[protocol] ?: AetherIdentityStatus(protocol, null)

        override suspend fun missingKeys(files: List<String>): List<String> {
            keysGate?.await()
            return files.filter { it in missingFiles }
        }
        override suspend fun clearPsiphonData() = clearer()
        override suspend fun psiphonRegions() = regions
        override suspend fun listenPort() = port
        override suspend fun takenPorts() = taken
        override suspend fun exitNodes() = nodes
        override suspend fun findExitNode(name: String) = found[name] ?: ExitNodeOutbound.NotFound
    }

    private val source = FakeSource()

    @OptIn(ExperimentalCoroutinesApi::class)
    @BeforeEach
    fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    @AfterEach
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun viewModel() = ServerAetherViewModel(mock<Application>(), source)

    private fun ServerAetherViewModel.texts() = log.value.map { it.text }

    private fun resource(id: Int, vararg args: String) = AetherLogText.Resource(id, args.toList())

    @Test
    fun startsIdleWithAnEmptyLogAndReportsWhetherTheCoreIsAvailable() {
        source.available = false
        val viewModel = viewModel()

        assertEquals(AetherScanState.Idle, viewModel.scanState.value)
        assertFalse(viewModel.isCoreAvailable.value)
        assertNull(viewModel.session.value)
        assertTrue(viewModel.log.value.isEmpty())
    }

    @Test
    fun theCommandIsBuiltOnTheListenPortOfTheSettings() {
        source.port = 20808
        assertEquals(20808, viewModel().listenPort.value)
    }

    @Test
    fun aScanStreamsTheCoreOutputAndEndsWithTheEndpointItFound() {
        val pending = CompletableDeferred<AetherScanResult?>()
        var scanned: ProfileItem? = null
        source.scanner = { profile, onOutput ->
            scanned = profile
            onOutput("[2026-09-11T10:00:00.000Z INFO  aether] [+] candidate ok 162.159.197.3:443 rtt=84ms")
            onOutput("   ")
            pending.await()
        }
        val viewModel = viewModel()

        viewModel.scan(profile)
        assertEquals(AetherScanState.Scanning, viewModel.scanState.value)
        assertSame(profile, scanned)

        pending.complete(found)

        assertEquals(AetherScanState.Found(found), viewModel.scanState.value)
        assertEquals(
            listOf(
                resource(R.string.aether_log_scan_started),
                AetherLogText.Raw("[+] candidate ok 162.159.197.3:443 rtt=84ms"),
                resource(R.string.aether_log_scan_found, "162.159.197.3:443"),
                resource(R.string.aether_log_masque_key_missing),
            ),
            viewModel.texts()
        )

        viewModel.onScanHandled()
        assertEquals(AetherScanState.Idle, viewModel.scanState.value)
    }

    @Test
    fun aScanThatFindsNothingSaysSo() {
        val viewModel = viewModel()

        viewModel.scan(profile)

        assertEquals(AetherScanState.NotFound, viewModel.scanState.value)
        val outcome = viewModel.log.value.first { it.text == resource(R.string.aether_scan_failed) }
        assertEquals(Log.WARN, outcome.priority)
    }

    @Test
    fun bothGoolHopsAreLoggedTogether() {
        val hops = AetherScanResult(AetherEndpoint("162.159.192.1", 2408), AetherEndpoint("188.114.96.1", 894))

        assertEquals(
            resource(R.string.aether_log_scan_found_hops, "162.159.192.1:2408", "188.114.96.1:894"),
            ServerAetherViewModel.scanOutcome(hops)
        )
    }

    @Test
    fun coreOutputKeepsItsLevelButLosesItsHeader() {
        source.scanner = { _, onOutput ->
            onOutput("[2026-09-11T10:00:00.000Z WARN  aether] [-] scan deadline reached")
            onOutput("Error: NoCleanEndpoint")
            null
        }
        val viewModel = viewModel()

        viewModel.scan(profile)

        val output = viewModel.log.value.filter { it.text is AetherLogText.Raw }
        assertEquals(listOf(Log.WARN, Log.ERROR), output.map { it.priority })
        assertEquals(
            listOf(AetherLogText.Raw("[-] scan deadline reached"), AetherLogText.Raw("Error: NoCleanEndpoint")),
            output.map { it.text }
        )
    }

    @Test
    fun aSecondActionWaitsForTheFirstToFinish() {
        val pending = CompletableDeferred<AetherScanResult?>()
        var scans = 0
        var clears = 0
        source.scanner = { _, _ -> scans++; pending.await() }
        source.clearer = { clears++; true }
        val viewModel = viewModel()

        viewModel.scan(profile)
        viewModel.scan(profile)
        viewModel.clearPsiphonData()
        assertEquals(1, scans)
        assertEquals(0, clears)

        pending.complete(null)
        viewModel.onScanHandled()
        viewModel.scan(profile)
        assertEquals(2, scans)
    }

    @Test
    fun cancellingAScanStopsItAndReturnsToIdle() {
        var stopped = false
        source.scanner = { _, _ ->
            try {
                awaitCancellation()
            } finally {
                stopped = true
            }
        }
        val viewModel = viewModel()

        viewModel.scan(profile)
        viewModel.cancelScan()

        assertTrue(stopped)
        assertEquals(AetherScanState.Idle, viewModel.scanState.value)
        assertEquals(resource(R.string.aether_log_scan_cancelled), viewModel.texts().last())
    }

    @Test
    fun cancellingWhenNothingRunsKeepsTheResult() {
        source.scanner = { _, _ -> found }
        val viewModel = viewModel()

        viewModel.scan(profile)
        viewModel.cancelScan()

        assertEquals(AetherScanState.Found(found), viewModel.scanState.value)
    }

    @Test
    fun handlingARunningScanDoesNotHideIt() {
        source.scanner = { _, _ -> awaitCancellation() }
        val viewModel = viewModel()

        viewModel.scan(profile)
        viewModel.onScanHandled()

        assertEquals(AetherScanState.Scanning, viewModel.scanState.value)
    }

    @Test
    fun theKeyStatusIsLoggedOnceUntilItChanges() {
        source.identities[AetherProtocol.MASQUE] = AetherIdentityStatus(AetherProtocol.MASQUE, oldKey)
        val viewModel = viewModel()

        viewModel.showIdentity(AetherProtocol.MASQUE)
        viewModel.showIdentity(AetherProtocol.MASQUE)
        viewModel.showIdentity(AetherProtocol.WIREGUARD)

        assertEquals(
            listOf(
                resource(R.string.aether_log_masque_key_ready, "a1b2c3d4…", "172.16.0.2", "2606:4700:110:8a36::1"),
                resource(R.string.aether_log_wireguard_key_missing),
            ),
            viewModel.texts()
        )
    }

    @Test
    fun aTwoHopProtocolReportsBothHopKeys() {
        for (protocol in listOf(AetherProtocol.GOOL, AetherProtocol.MIM, AetherProtocol.WG_OVER_MASQUE)) {
            val status = AetherIdentityStatus(protocol, oldKey, null)

            assertEquals(
                listOf(
                    resource(R.string.aether_log_outer_key_ready, "a1b2c3d4…", "172.16.0.2", "2606:4700:110:8a36::1"),
                    resource(R.string.aether_log_inner_key_missing),
                ),
                ServerAetherViewModel.identityLines(status)
            )
        }
    }

    @Test
    fun aCancelledScanStaysBusyUntilItHasStopped() {
        val stopped = CompletableDeferred<Unit>()
        var scans = 0
        var clears = 0
        source.clearer = { clears++; true }
        source.scanner = { _, _ ->
            scans++
            try {
                awaitCancellation()
            } finally {
                // The core is still being ended, as a real one takes a moment to.
                withContext(NonCancellable) { stopped.await() }
            }
        }
        val viewModel = viewModel()

        viewModel.scan(profile)
        viewModel.cancelScan()

        assertEquals(AetherScanState.Scanning, viewModel.scanState.value)
        viewModel.scan(profile)
        viewModel.clearPsiphonData()
        viewModel.cancelScan()
        assertEquals(1, scans)
        assertEquals(0, clears)
        assertEquals(1, viewModel.texts().count { it == resource(R.string.aether_log_scan_cancelled) })

        stopped.complete(Unit)

        assertEquals(AetherScanState.Idle, viewModel.scanState.value)
        viewModel.scan(profile)
        assertEquals(2, scans)
    }

    @Test
    fun aLiveSessionIsReportedWhenTheScreenOpens() {
        source.session = AetherSession(AetherProtocol.MASQUE)

        assertEquals(AetherSession(AetherProtocol.MASQUE), viewModel().session.value)
    }

    @Test
    fun theExitCountriesOnOfferComeFromTheServerList() {
        assertTrue(viewModel().psiphonRegions.value.isEmpty())
        source.regions = listOf("DE", "US")
        assertEquals(listOf("DE", "US"), viewModel().psiphonRegions.value)
    }

    @Test
    fun psiphonDataIsNotClearedUnderALiveSessionAndTheLogTellsTheOutcome() {
        var clears = 0
        source.clearer = { clears++; true }
        val viewModel = viewModel()

        source.session = AetherSession(AetherProtocol.MASQUE)
        viewModel.clearPsiphonData()
        assertEquals(0, clears)
        val blocked = viewModel.log.value.single()
        assertEquals(resource(R.string.aether_psiphon_clear_blocked), blocked.text)
        assertEquals(Log.WARN, blocked.priority)

        source.session = null
        viewModel.clearPsiphonData()
        assertEquals(1, clears)
        val cleared = viewModel.log.value.last()
        assertEquals(resource(R.string.aether_log_psiphon_cleared), cleared.text)
        assertEquals(Log.INFO, cleared.priority)

        source.clearer = { clears++; false }
        viewModel.clearPsiphonData()
        assertEquals(2, clears)
        val failed = viewModel.log.value.last()
        assertEquals(resource(R.string.aether_log_psiphon_clear_failed), failed.text)
        assertEquals(Log.ERROR, failed.priority)
    }

    @Test
    fun aScanIsNotStartedOnTheKeyOfALiveSession() {
        var scans = 0
        source.scanner = { _, _ -> scans++; found }
        val viewModel = viewModel()

        source.session = AetherSession(AetherProtocol.MASQUE)
        viewModel.scan(profile)

        assertEquals(0, scans)
        assertEquals(AetherScanState.Idle, viewModel.scanState.value)
        assertEquals(AetherSession(AetherProtocol.MASQUE), viewModel.session.value)
        val blocked = viewModel.log.value.single()
        assertEquals(resource(R.string.aether_scan_blocked), blocked.text)
        assertEquals(Log.WARN, blocked.priority)

        // Only the listener was visible, so the session's key is unknown and the scan stays blocked.
        source.session = AetherSession(protocol = null)
        viewModel.scan(profile)
        assertEquals(0, scans)

        // A WireGuard session uses another key than this MASQUE profile, so the scan goes ahead.
        source.session = AetherSession(AetherProtocol.WIREGUARD)
        viewModel.scan(profile)
        assertEquals(1, scans)
        assertEquals(AetherScanState.Found(found), viewModel.scanState.value)
    }

    @Test
    fun aScanWhoseKeysAreMissingAsksFirstAndGoesAheadWhenToldTo() {
        var scans = 0
        source.scanner = { _, _ -> scans++; found }
        source.missingFiles += AetherIdentityManager.MASQUE_FILE
        val viewModel = viewModel()
        assertNull(viewModel.keysCheck.value)

        viewModel.scan(profile)
        assertEquals(0, scans)
        assertEquals(AetherScanState.Idle, viewModel.scanState.value)
        assertEquals(AetherKeysCheck.Missing(scan = true, profile = profile), viewModel.keysCheck.value)
        assertTrue(viewModel.log.value.isEmpty())

        viewModel.onKeysCheckHandled()
        assertNull(viewModel.keysCheck.value)
        viewModel.scan(profile, anyway = true)
        assertEquals(1, scans)
        assertNull(viewModel.keysCheck.value)
        assertEquals(AetherScanState.Found(found), viewModel.scanState.value)
    }

    @Test
    fun theProfilesThatCanBeTheExitNodeAreRead() {
        source.nodes = listOf(AetherExitNode("germany", 1), AetherExitNode("france", 2))
        assertEquals(source.nodes, viewModel().exitNodes.value)
    }

    @Test
    fun aScanDoesNotDialOutThroughAnExitNodeNameThatFindsNoProfileOrSeveral() {
        var scans = 0
        source.scanner = { _, _ -> scans++; null }
        val viewModel = viewModel()
        val noded = profile.copy(aetherExitNode = "germany ")

        // Renamed or deleted since the screen opened.
        viewModel.scan(noded)
        assertEquals(0, scans)
        assertEquals(AetherScanState.Idle, viewModel.scanState.value)
        assertEquals(resource(R.string.toast_profile_name_not_found, "germany"), viewModel.texts().last())

        // The name of two profiles by now.
        source.found["germany"] = ExitNodeOutbound.SameName
        viewModel.scan(noded)
        assertEquals(0, scans)
        assertEquals(resource(R.string.toast_profile_name_duplicate, "germany"), viewModel.texts().last())

        source.found["germany"] = ExitNodeOutbound.Built(V2rayConfig.OutboundBean(tag = "proxy", protocol = "vless"))
        viewModel.scan(noded)
        assertEquals(1, scans)
    }

    @Test
    fun aScanNeedsOnlyTheKeysOfItsProtocol() {
        var scans = 0
        source.scanner = { _, _ -> scans++; null }
        source.missingFiles += listOf(AetherIdentityManager.MASQUE_FILE, AetherIdentityManager.MASQUE_INNER_FILE)
        val viewModel = viewModel()

        viewModel.scan(profile.copy(aetherProtocol = AetherProtocol.WIREGUARD.type))
        assertEquals(1, scans)
        assertNull(viewModel.keysCheck.value)

        viewModel.onScanHandled()
        viewModel.scan(profile.copy(aetherProtocol = AetherProtocol.MIM.type))
        assertEquals(1, scans)
        assertEquals(AetherKeysCheck.Missing(scan = true, profile = profile.copy(aetherProtocol = AetherProtocol.MIM.type)), viewModel.keysCheck.value)
    }

    @Test
    fun wireGuardOverMasqueWarnsWhenItsOuterMasqueKeyOrItsInnerWireGuardKeyIsMissing() {
        var scans = 0
        source.scanner = { _, _ -> scans++; null }
        val viewModel = viewModel()
        val goolOverMasque = profile.copy(aetherProtocol = AetherProtocol.WG_OVER_MASQUE.type)

        for (missing in listOf(AetherIdentityManager.MASQUE_FILE, AetherIdentityManager.MASQUE_GOOL_FILE)) {
            source.missingFiles.clear()
            source.missingFiles += missing

            viewModel.checkKeysBeforeSave(goolOverMasque)
            assertEquals(AetherKeysCheck.Missing(scan = false, profile = goolOverMasque), viewModel.keysCheck.value, missing)
            viewModel.onKeysCheckHandled()

            viewModel.scan(goolOverMasque)
            assertEquals(AetherKeysCheck.Missing(scan = true, profile = goolOverMasque), viewModel.keysCheck.value, missing)
            assertEquals(0, scans, missing)
            viewModel.onKeysCheckHandled()
        }

        // With both of its keys there nothing is asked; the keys of the other protocols do not count.
        source.missingFiles.clear()
        source.missingFiles += listOf(
            AetherIdentityManager.WIREGUARD_FILE,
            AetherIdentityManager.WIREGUARD_INNER_FILE,
            AetherIdentityManager.MASQUE_INNER_FILE,
        )
        viewModel.checkKeysBeforeSave(goolOverMasque)
        assertEquals(AetherKeysCheck.SaveReady(goolOverMasque), viewModel.keysCheck.value)
        viewModel.onKeysCheckHandled()
        viewModel.scan(goolOverMasque)
        assertNull(viewModel.keysCheck.value)
        assertEquals(1, scans)
    }

    @Test
    fun aSaveLooksTheExitNodeUpAfreshAndIsRefusedForOneItCannotUse() {
        val viewModel = viewModel()
        val noded = profile.copy(aetherExitNode = " germany ")

        // Renamed or deleted since the screen opened, the name of two profiles by now, one that gives no outbound, or
        // one whose ECH outbound cannot go beside it: the list read when the screen opened cannot tell.
        for (problem in listOf(ExitNodeOutbound.NotFound, ExitNodeOutbound.SameName, ExitNodeOutbound.NoOutbound, ExitNodeOutbound.EchUnusable)) {
            source.found["germany"] = problem
            viewModel.checkKeysBeforeSave(noded)
            assertEquals(AetherKeysCheck.Refused(problem.message, listOf("germany")), viewModel.keysCheck.value, problem.toString())
            viewModel.onKeysCheckHandled()
        }

        source.found["germany"] = ExitNodeOutbound.Built(V2rayConfig.OutboundBean(tag = "proxy", protocol = "vless"))
        viewModel.checkKeysBeforeSave(noded)
        assertEquals(AetherKeysCheck.SaveReady(noded), viewModel.keysCheck.value)
        viewModel.onKeysCheckHandled()

        // Freedom is looked up nowhere.
        source.found.clear()
        viewModel.checkKeysBeforeSave(profile)
        assertEquals(AetherKeysCheck.SaveReady(profile), viewModel.keysCheck.value)
    }

    @Test
    fun theScreenHoldsTheProfileCheckedUntilItIsEdited() {
        val checked = profile.copy(remarks = "warp")

        val port = source.port
        assertTrue(holdsChecked(checked.copy(), checked, port))
        // A new profile is added anew when the screen's activity is recreated, as on a rotation: that is no edit.
        assertTrue(holdsChecked(checked.copy(addedTime = checked.addedTime + 1_000), checked, port))
        assertFalse(holdsChecked(checked.copy(remarks = "edited"), checked, port))
        assertFalse(holdsChecked(checked.copy(aetherProtocol = AetherProtocol.WIREGUARD.type), checked, port))
        // A cleared ECH resolver comes back as the default once the screen is recreated: saved, the two are one.
        val cleared = checked.copy(aetherEch = true, aetherEchDns = null)
        assertTrue(holdsChecked(cleared.copy(aetherEchDns = AppConfig.AETHER_ECH_DNS), cleared, port))
        assertFalse(holdsChecked(cleared.copy(aetherEchDns = "udp://9.9.9.9"), cleared, port))
    }

    @Test
    fun aCheckALaterOneReplacesOrTheScreenMovedOnFromSaysNothing() {
        val gate = CompletableDeferred<Unit>()
        source.keysGate = gate
        val viewModel = viewModel()
        val first = profile.copy(remarks = "first")
        val second = profile.copy(remarks = "second")

        viewModel.checkKeysBeforeSave(first)
        source.keysGate = null
        viewModel.checkKeysBeforeSave(second)
        assertEquals(AetherKeysCheck.SaveReady(second), viewModel.keysCheck.value)
        viewModel.onKeysCheckHandled()
        gate.complete(Unit)
        assertNull(viewModel.keysCheck.value)

        // One still running when the screen acts on another outcome, as when it goes to get the keys, says nothing either.
        val later = CompletableDeferred<Unit>()
        source.keysGate = later
        viewModel.checkKeysBeforeSave(first)
        viewModel.onKeysCheckHandled()
        later.complete(Unit)
        assertNull(viewModel.keysCheck.value)
    }

    @Test
    fun aSaveGoesOnOnlyWhenTheKeysTheProfileNeedsAreThere() {
        val viewModel = viewModel()

        viewModel.checkKeysBeforeSave(profile)
        assertEquals(AetherKeysCheck.SaveReady(profile), viewModel.keysCheck.value)
        // The outcome carries the profile checked: the screen saves it only while it holds that one still.
        assertSame(profile, (viewModel.keysCheck.value as AetherKeysCheck.SaveReady).profile)
        viewModel.onKeysCheckHandled()
        // Or, when the check got a normalized copy of it, the profile as the screen held it.
        val held = profile.copy(aetherEchDns = "udp://1.1.1.1")
        viewModel.checkKeysBeforeSave(profile, held)
        assertSame(held, (viewModel.keysCheck.value as AetherKeysCheck.SaveReady).profile)
        viewModel.onKeysCheckHandled()
        source.missingFiles += AetherIdentityManager.MASQUE_FILE
        viewModel.checkKeysBeforeSave(profile, held)
        assertSame(held, (viewModel.keysCheck.value as AetherKeysCheck.Missing).profile)
        source.missingFiles.clear()
        viewModel.onKeysCheckHandled()
        assertNull(viewModel.keysCheck.value)

        // A MASQUE profile needs no inner hop key; masque-in-masque does.
        source.missingFiles += AetherIdentityManager.MASQUE_INNER_FILE
        viewModel.checkKeysBeforeSave(profile)
        assertEquals(AetherKeysCheck.SaveReady(profile), viewModel.keysCheck.value)
        viewModel.checkKeysBeforeSave(profile.copy(aetherProtocol = AetherProtocol.MIM.type))
        assertEquals(AetherKeysCheck.Missing(scan = false, profile = profile.copy(aetherProtocol = AetherProtocol.MIM.type)), viewModel.keysCheck.value)

        // WireGuard over MASQUE needs the WireGuard key it carries as well, which the WARP keys page gets.
        source.missingFiles += AetherIdentityManager.MASQUE_GOOL_FILE
        viewModel.checkKeysBeforeSave(profile.copy(aetherProtocol = AetherProtocol.WG_OVER_MASQUE.type))
        assertEquals(AetherKeysCheck.Missing(scan = false, profile = profile.copy(aetherProtocol = AetherProtocol.WG_OVER_MASQUE.type)), viewModel.keysCheck.value)
        viewModel.onKeysCheckHandled()

        // A command written by hand counts as it runs.
        source.missingFiles += AetherIdentityManager.WIREGUARD_FILE
        viewModel.checkKeysBeforeSave(profile.copy(aetherCommand = "aether --bind 127.0.0.1:10819 --protocol wg"))
        assertEquals(AetherKeysCheck.Missing(scan = false, profile = profile.copy(aetherCommand = "aether --bind 127.0.0.1:10819 --protocol wg")), viewModel.keysCheck.value)

        // Psiphon alone needs no WARP key at all.
        source.missingFiles += AetherIdentityManager.KEY_FILES
        viewModel.checkKeysBeforeSave(profile.copy(aetherPsiphon = "only"))
        assertEquals(AetherKeysCheck.SaveReady(profile.copy(aetherPsiphon = "only")), viewModel.keysCheck.value)
    }

    @Test
    fun theLogKeepsOnlyTheLatestEntries() {
        source.scanner = { _, onOutput ->
            repeat(ServerAetherViewModel.LOG_CAPACITY + 50) { onOutput("line $it") }
            null
        }
        val viewModel = viewModel()

        viewModel.scan(profile)

        val entries = viewModel.log.value
        assertEquals(ServerAetherViewModel.LOG_CAPACITY, entries.size)
        assertEquals(entries.map { it.id }.sorted(), entries.map { it.id })
        assertTrue(entries.none { it.text == AetherLogText.Raw("line 0") })
    }

    @Test
    fun thePortsAProfileIsCheckedOnAreReadAsTheScreenOpens() {
        val viewModel = viewModel()

        assertEquals(source.port, viewModel.listenPort.value)
        assertEquals(source.taken, viewModel.takenPorts.value)
    }
}
