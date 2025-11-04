package com.adm.kiosk.data.db

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

@Dao
interface WebLinkDao {

    @Query("SELECT * FROM web_links ORDER BY position ASC, id ASC")
    fun observeAll(): Flow<List<WebLink>>

    @Query("SELECT * FROM web_links ORDER BY position ASC, id ASC")
    suspend fun getAll(): List<WebLink>

    @Query("SELECT * FROM web_links WHERE id = :id LIMIT 1")
    suspend fun getById(id: Long): WebLink?

    @Query("SELECT * FROM web_links ORDER BY position ASC, id ASC LIMIT 1")
    suspend fun getFirst(): WebLink?

    @Query("SELECT COUNT(*) FROM web_links")
    suspend fun count(): Int

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(link: WebLink): Long

    @Update
    suspend fun update(link: WebLink)

    @Delete
    suspend fun delete(link: WebLink)

    @Query("DELETE FROM web_links WHERE id = :id")
    suspend fun deleteById(id: Long)
}
