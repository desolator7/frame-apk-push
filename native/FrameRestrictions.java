/* SPDX-License-Identifier: MIT */
/** Start Android's shipped RestrictionsManagerService in this title's container. */
public final class FrameRestrictions {
    /** SystemServer normally provides local objects; this process uses Binder proxies. */
    private static void bridgeService(String name, String interfaceName) throws Exception {
        Class<?> manager = Class.forName("android.os.ServiceManager");
        Object binder = manager.getMethod("getService", String.class).invoke(null, name);
        if (binder == null) return;
        Class<?> binderType = Class.forName("android.os.IBinder");
        Class<?> serviceType = Class.forName(interfaceName);
        Object remote = Class.forName(interfaceName + "$Stub").getMethod("asInterface", binderType).invoke(null, binder);
        Object bridge = java.lang.reflect.Proxy.newProxyInstance(serviceType.getClassLoader(),
            new Class<?>[] {binderType, serviceType}, new Bridge(binder, remote));
        java.lang.reflect.Field cache = manager.getDeclaredField("sCache");
        cache.setAccessible(true);
        @SuppressWarnings("unchecked") java.util.Map<String, Object> services =
            (java.util.Map<String, Object>) cache.get(null);
        services.put(name, bridge);
    }

    private static final class Bridge implements java.lang.reflect.InvocationHandler {
        private final Object binder, remote;
        Bridge(Object binder, Object remote) { this.binder = binder; this.remote = remote; }
        public Object invoke(Object proxy, java.lang.reflect.Method method, Object[] args) throws Throwable {
            Object target = method.getDeclaringClass().getName().equals("android.os.IBinder") ? binder : remote;
            try { return method.invoke(target, args); }
            catch (java.lang.reflect.InvocationTargetException error) { throw error.getCause(); }
        }
    }

    public static void main(String[] args) {
        try {
            Class<?> looper = Class.forName("android.os.Looper");
            looper.getMethod("prepareMainLooper").invoke(null);
            Class<?> activityThread = Class.forName("android.app.ActivityThread");
            Object thread = activityThread.getMethod("systemMain").invoke(null);
            Object context = activityThread.getMethod("getSystemContext").invoke(thread);
            bridgeService("user", "android.os.IUserManager");
            bridgeService("device_policy", "android.app.admin.IDevicePolicyManager");
            Class<?> serviceClass = Class.forName("com.android.server.restrictions.RestrictionsManagerService");
            Object service = serviceClass.getConstructor(Class.forName("android.content.Context")).newInstance(context);
            serviceClass.getMethod("onStart").invoke(service);
            Class.forName("android.os.SystemProperties").getMethod("set", String.class, String.class)
                .invoke(null, "frame.restrictions.ready", "1");
            System.out.println("Frame: RestrictionsManagerService ready");
            looper.getMethod("loop").invoke(null);
        } catch (Throwable error) {
            error.printStackTrace();
            System.exit(1);
        }
    }
}
