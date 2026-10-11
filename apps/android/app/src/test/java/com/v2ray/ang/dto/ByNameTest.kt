package com.v2ray.ang.dto

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Test

class ByNameTest {

    private fun find(name: String?, vararg names: String): ByName<String> = ByName.find(name, names.asSequence()) { it }

    @Test
    fun aNameFindsTheOneProfileThatHasIt() {
        assertEquals(ByName.One("germany"), find("germany", "france", "germany", "germany 2"))
    }

    @Test
    fun namesAreToldApartWithoutTheSpacesAroundThem() {
        assertEquals(ByName.One(" germany "), find("germany", " germany "))
        assertEquals(ByName.One("germany"), find(" germany  ", "germany"))
        // Inside a name, and in the case of its letters, they count.
        assertEquals(ByName.None, find("Germany", "germany"))
        assertEquals(ByName.None, find("ger many", "germany"))
    }

    @Test
    fun aNameNoProfileHasAnyMoreFindsNone() {
        assertEquals(ByName.None, find("germany", "france", "germany-renamed"))
        assertEquals(ByName.None, find("germany"))
    }

    @Test
    fun aNameSeveralProfilesHaveFindsSeveral() {
        assertEquals(ByName.Several, find("germany", "germany", "france", " germany"))
    }

    @Test
    fun aBlankNameFindsNoneEvenWhereProfilesHaveNoName() {
        assertEquals(ByName.None, find("", "", "france"))
        assertEquals(ByName.None, find("  ", " "))
        assertEquals(ByName.None, find(null, ""))
    }

    @Test
    fun theSearchEndsAtTheSecondProfileWithTheName() {
        // The profiles of a long list are decoded as the search goes; those after the second are not.
        val read = mutableListOf<String>()
        val names = sequenceOf("germany", "france", "germany", "spain").onEach { read += it }
        assertEquals(ByName.Several, ByName.find("germany", names) { it })
        assertEquals(listOf("germany", "france", "germany"), read)
    }
}
