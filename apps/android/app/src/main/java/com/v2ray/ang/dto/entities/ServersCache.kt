package com.v2ray.ang.dto.entities

data class ServersCache(
    val guid: String,
    val profile: ProfileItem,
    val testDelayMillis: Long = 0L,
    val countryCode: String? = null,
    val ipAddress: String? = null,
    val securityInfo: String? = null,
    val sanctionsAccessible: Boolean? = null,
    val sanctionsPassed: Int = 0,
    val sanctionsTotal: Int = 0,
)
