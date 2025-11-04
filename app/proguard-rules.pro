# Keep WebView JS interface members (used by injected bridge, if any)
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}

# Room
-keep class * extends androidx.room.RoomDatabase
-dontwarn androidx.room.paging.**

# Keep DeviceAdminReceiver (referenced from manifest/xml only)
-keep class com.adm.kiosk.kiosk.** { *; }
