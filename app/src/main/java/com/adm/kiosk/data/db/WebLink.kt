package com.adm.kiosk.data.db

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * A web page registered by the administrator to be displayed in kiosk mode.
 */
@Entity(tableName = "web_links")
data class WebLink(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,

    /** Human readable identification (Nome do link). */
    val name: String,

    /** Target address (URL/Link). */
    val url: String,

    /** Category / type of page (Tipo de página). */
    val category: String = "",

    /** Ordering position in the admin list. */
    val position: Int = 0,

    /** Per-link zoom override in percent (0 = use global setting). */
    val zoomPercent: Int = 0,

    /** Per-link refresh interval in seconds (-1 = use global setting, 0 = disabled). */
    val refreshSeconds: Int = -1,
)
