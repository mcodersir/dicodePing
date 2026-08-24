package com.v2ray.ang.dto.entities

data class ServerAffiliationInfo(
    var testDelayMillis: Long = 0L,
    var countryCode: String? = null,
    var ipAddress: String? = null,
    var sanctionsAccessible: Boolean? = null,
    var sanctionsPassed: Int = 0,
    var sanctionsTotal: Int = 0
)
