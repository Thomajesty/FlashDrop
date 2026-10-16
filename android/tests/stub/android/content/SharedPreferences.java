package android.content;

/** 测试桩：SharedPreferences（仅 JVM 单元测试用） */
public interface SharedPreferences {
    String getString(String key, String defValue);
    int getInt(String key, int defValue);
    boolean getBoolean(String key, boolean defValue);
    long getLong(String key, long defValue);
    Editor edit();

    interface Editor {
        Editor putString(String key, String value);
        Editor putInt(String key, int value);
        Editor putBoolean(String key, boolean value);
        Editor putLong(String key, long value);
        void apply();
    }
}
