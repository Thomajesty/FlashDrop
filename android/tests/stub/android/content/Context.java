package android.content;

/**
 * 测试桩：Android Context（仅 JVM 单元测试用）。
 *
 * android.jar 里的 Context 方法体全是 throw new RuntimeException("Stub!")，
 * 直接跑会崩。这里提供一个"全部安全返回"的替代实现，
 * classpath 中排在 android.jar 之前即可遮蔽它（与 android/os/Handler 桩同一套路）。
 *
 * 只实现 FlashNode/FdUtil/FdProto 路径会碰到的方法；其余一律返回 null。
 */
public class Context {
    public static final String WIFI_SERVICE = "wifi";
    public static final String POWER_SERVICE = "power";
    public static final String CLIPBOARD_SERVICE = "clipboard";
    public static final int MODE_PRIVATE = 0;

    public Context getApplicationContext() {
        return this;
    }

    public Object getSystemService(String name) {
        return null;
    }

    public java.io.File getCacheDir() {
        return new java.io.File(".");
    }

    public java.io.File getFilesDir() {
        return new java.io.File(".");
    }

    public android.content.ContentResolver getContentResolver() {
        return null;
    }

    public String getPackageName() {
        return "com.flashdrop.app.test";
    }

    public SharedPreferences getSharedPreferences(String name, int mode) {
        return null;
    }

    public android.content.res.Resources getResources() {
        return null;
    }

}