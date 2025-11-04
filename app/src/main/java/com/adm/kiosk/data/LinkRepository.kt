package com.adm.kiosk.data

import android.content.Context
import com.adm.kiosk.data.db.KioskDatabase
import com.adm.kiosk.data.db.WebLink
import com.adm.kiosk.data.db.WebLinkDao
import kotlinx.coroutines.flow.Flow

class LinkRepository private constructor(private val dao: WebLinkDao) {

    fun observeAll(): Flow<List<WebLink>> = dao.observeAll()

    suspend fun getAll(): List<WebLink> = dao.getAll()

    suspend fun getById(id: Long): WebLink? = dao.getById(id)

    suspend fun getFirst(): WebLink? = dao.getFirst()

    suspend fun count(): Int = dao.count()

    suspend fun add(link: WebLink): Long = dao.insert(link)

    suspend fun update(link: WebLink) = dao.update(link)

    suspend fun delete(link: WebLink) = dao.delete(link)

    suspend fun deleteById(id: Long) = dao.deleteById(id)

    companion object {
        @Volatile
        private var INSTANCE: LinkRepository? = null

        fun get(context: Context): LinkRepository =
            INSTANCE ?: synchronized(this) {
                INSTANCE ?: LinkRepository(KioskDatabase.get(context).webLinkDao())
                    .also { INSTANCE = it }
            }
    }
}
