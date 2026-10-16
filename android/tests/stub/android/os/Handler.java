package android.os;

import java.util.ArrayList;
import java.util.List;

/**
 * 测试用 android.os.Handler 桩（同步语义，便于断言）。
 *
 * <p>真实 SDK 的 android.jar 里 Handler.post() 直接抛 RuntimeException("Stub!")，
 * 而 FlashApp.flushPendingSendsAsync() 依赖它把结果切回"主线程"提交队列。
 *
 * <p>这里给的是**同步**实现：
 * <ul>
 *   <li>{@link #post(Runnable)} —— 立即执行（等价于 UI 线程里同步跑完）</li>
 *   <li>{@link #postDelayed(Runnable, long)} —— <b>只登记不执行</b>，
 *       避免重试任务自我递归；测试可据此断言"已安排重试"</li>
 * </ul>
 */
public class Handler {
    /** 记录被 postDelayed 的任务，供测试断言"周期重试已挂上" */
    public static final List<Runnable> DELAYED = new ArrayList<>();

    private final Looper looper;

    public Handler() {
        this.looper = Looper.getMainLooper();
    }

    public Handler(Looper l) {
        this.looper = l;
    }

    public Looper getLooper() {
        return looper;
    }

    /** 同步执行：测试里等价于"立刻在 UI 线程跑完" */
    public boolean post(Runnable r) {
        if (r != null) r.run();
        return true;
    }

    public boolean postDelayed(Runnable r, long delayMillis) {
        if (r != null) DELAYED.add(r);
        return true;
    }

    public void removeCallbacks(Runnable r) {
        DELAYED.remove(r);
    }

    public void removeCallbacksAndMessages(Object token) {
        DELAYED.clear();
    }
}