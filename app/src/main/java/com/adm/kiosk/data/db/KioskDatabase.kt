package com.adm.kiosk.data.db

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

@Database(
    entities = [WebLink::class],
    version = 1,
    exportSchema = false,
)
abstract class KioskDatabase : RoomDatabase() {

    abstract fun webLinkDao(): WebLinkDao

    companion object {
        @Volatile
        private var INSTANCE: KioskDatabase? = null

        fun get(context: Context): KioskDatabase {
            return INSTANCE ?: synchronized(this) {
                INSTANCE ?: Room.databaseBuilder(
                    context.applicationContext,
                    KioskDatabase::class.java,
                    "kiosk.db",
                )
                    .fallbackToDestructiveMigration()
                    .build()
                    .also { INSTANCE = it }
            }
        }
    }
}
