package android.media;

/**
 * 测试桩：MediaScannerConnection（仅 JVM 单元测试用）。
 * android.jar 里的方法体全是 throw new RuntimeException("Stub!")，
 * 会让 FlashNode.saveToDownloads 的 API<29 分支直接崩掉。
 */
public class MediaScannerConnection {
    public static void scanFile(android.content.Context ctx, String[] paths, String[] mimeTypes,
                                ScanResultListener callback) {
        // 测试桩：什么都不做
    }

    public interface ScanResultListener {
        void onScanCompleted(String path, android.net.Uri uri);
    }
}