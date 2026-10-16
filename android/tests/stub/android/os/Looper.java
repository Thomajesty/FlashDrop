package android.os;

/**
 * 测试用 android.os.Looper 桩。
 *
 * 真实 SDK 的 android.jar 里所有方法都直接抛 RuntimeException("Stub!")，
 * 而 FlashApp 的待发队列要用 Handler 把结果送回"主线程"。
 * 这里给一个能真跑的最小实现，让纯逻辑测试可以在普通 JVM 里驱动真实 FlashApp 代码。
 *
 * 放在 classpath 中 android.jar **之前**即可覆盖官方桩。
 */
public class Looper {
    private static final Looper MAIN = new Looper();

    public static Looper getMainLooper() {
        return MAIN;
    }
}