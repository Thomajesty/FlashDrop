package com.flashdrop.app;

/**
 * 测试用 R 桩：aapt2 生成的 R 类在真实构建里才有，
 * 但 FlashNode 里有一处 R.raw.fd_tls 引用，纯逻辑测试编译时需要它存在。
 * 这里的值无意义 —— 相关代码路径（读 TLS 证书）在离线队列测试里不会走到。
 */
public final class R {
    public static final class raw {
        public static final int fd_tls = 1;
    }
    public static final class drawable {
        public static final int bubble_in = 2;
        public static final int bubble_in_light = 3;
    }
}