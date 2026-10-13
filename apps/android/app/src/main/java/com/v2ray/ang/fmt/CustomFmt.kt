package com.v2ray.ang.fmt

import com.v2ray.ang.dto.V2rayConfig
import com.v2ray.ang.dto.entities.ProfileItem
import com.v2ray.ang.enums.EConfigType
import com.v2ray.ang.util.JsonUtil

object CustomFmt : FmtBase() {
    /**
     * Parses a JSON string into a ProfileItem object.
     *
     * @param str the JSON string to parse
     * @return the parsed ProfileItem object, or null if parsing fails
     */
    fun parse(str: String): ProfileItem {
        val config = ProfileItem.create(EConfigType.CUSTOM)

        if (com.v2ray.ang.core.SingBoxConfig.isConfig(str)) {
            val json = com.google.gson.JsonParser.parseString(str).asJsonObject
            val outbound = json.getAsJsonArray("outbounds")?.firstOrNull { it.asJsonObject.has("server") }?.asJsonObject
                ?: json.getAsJsonArray("endpoints")?.firstOrNull()?.asJsonObject
            config.remarks = json.get("remarks")?.asString ?: "sing-box"
            config.server = outbound?.get("server")?.asString
            config.serverPort = outbound?.get("server_port")?.asString
            return config
        }
        val fullConfig = JsonUtil.fromJson(str, V2rayConfig::class.java)
        val outbound = fullConfig?.getProxyOutbound()

        config.remarks = fullConfig?.remarks ?: System.currentTimeMillis().toString()
        config.server = outbound?.getServerAddress()
        config.serverPort = outbound?.getServerPort()?.toString()

        return config
    }
}