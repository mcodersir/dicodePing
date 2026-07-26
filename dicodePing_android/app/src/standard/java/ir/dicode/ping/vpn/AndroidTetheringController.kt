package ir.dicode.ping.vpn

/** Public build: advanced tethering is unavailable. */
class AndroidTetheringController {
    fun start(usb: Boolean, hotspot: Boolean): Result<Unit> = runCatching {
        require(!usb && !hotspot) {
            "VPN sharing is available only in the separately identified rooted build"
        }
    }
    fun stop() = Unit
}
