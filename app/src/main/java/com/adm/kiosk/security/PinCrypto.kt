package com.adm.kiosk.security

import android.util.Base64
import java.security.MessageDigest
import java.security.SecureRandom

/**
 * Salted SHA-256 hashing for the 4-digit administration PIN.
 * The clear PIN is never persisted; only salt + hash are stored.
 */
object PinCrypto {

    private const val ITERATIONS = 10_000

    fun newSalt(): String {
        val bytes = ByteArray(16)
        SecureRandom().nextBytes(bytes)
        return Base64.encodeToString(bytes, Base64.NO_WRAP)
    }

    fun hash(pin: String, salt: String): String {
        val md = MessageDigest.getInstance("SHA-256")
        var data = (salt + pin).toByteArray(Charsets.UTF_8)
        repeat(ITERATIONS) {
            md.reset()
            data = md.digest(data)
        }
        return Base64.encodeToString(data, Base64.NO_WRAP)
    }

    fun verify(pin: String, salt: String, expectedHash: String): Boolean {
        val actual = hash(pin, salt)
        // constant-time comparison
        return constantTimeEquals(actual, expectedHash)
    }

    private fun constantTimeEquals(a: String, b: String): Boolean {
        if (a.length != b.length) return false
        var result = 0
        for (i in a.indices) {
            result = result or (a[i].code xor b[i].code)
        }
        return result == 0
    }
}
