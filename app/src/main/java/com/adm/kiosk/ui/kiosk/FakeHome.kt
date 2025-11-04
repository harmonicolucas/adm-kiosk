package com.adm.kiosk.ui.kiosk

import android.app.Activity
import android.os.Bundle

/** Never shown: only exists so its HOME filter can be toggled (see HomeLauncher). */
class FakeHome : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        finish()
    }
}
