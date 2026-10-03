/* SPDX-License-Identifier: MIT */
import java.io.IOException;
import java.net.SocketTimeoutException;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/** Automatic per-title WebXR preloader. Does not depend on ADB or a desktop. */
public final class FrameBrowserXR {
    static final Path STATUS = Paths.get("/data/local/tmp/frame-webxr.json");
    private final String packageName, source, digest;
    private final Path statusPath;
    private final Map<Integer, Pending> pending = new HashMap<>();
    private final Set<String> sessions = new HashSet<>();
    private FrameDevtools websocket;
    private int sequence, injections, failures;
    private boolean attached;

    // Use Android's shipped org.json without requiring an SDK at build time.
    static final class J {
        static final Class<?> TYPE;
        static { try { TYPE = Class.forName("org.json.JSONObject"); }
                 catch (Exception error) { throw new ExceptionInInitializerError(error); } }
        final Object value;
        J() throws Exception { value = TYPE.getConstructor().newInstance(); }
        J(String text) throws Exception { value = TYPE.getConstructor(String.class).newInstance(text); }
        J(Object value) { this.value = value; }
        Object get(String key) throws Exception { return TYPE.getMethod("opt", String.class).invoke(value, key); }
        J child(String key) throws Exception { Object value = get(key); return TYPE.isInstance(value) ? new J(value) : new J(); }
        String string(String key) throws Exception { Object v = get(key); return v instanceof String ? (String) v : ""; }
        int number(String key) throws Exception { Object v = get(key); return v instanceof Number ? ((Number) v).intValue() : 0; }
        boolean has(String key) throws Exception { return (Boolean) TYPE.getMethod("has", String.class).invoke(value, key); }
        J put(String key, Object v) throws Exception {
            TYPE.getMethod("put", String.class, Object.class).invoke(value, key, v instanceof J ? ((J) v).value : v);
            return this;
        }
        public String toString() { return value.toString(); }
    }

    static final class Pending {
        final String session, method;
        final int stage;
        final long deadline = System.nanoTime() + 5_000_000_000L;
        Pending(String session, String method, int stage) { this.session = session; this.method = method; this.stage = stage; }
    }

    FrameBrowserXR(String packageName, String source) throws Exception {
        this(packageName, source, STATUS);
    }

    FrameBrowserXR(String packageName, String source, Path statusPath) throws Exception {
        this.packageName = packageName; this.source = source;
        this.statusPath = statusPath;
        byte[] bytes = MessageDigest.getInstance("SHA-256").digest(source.getBytes(StandardCharsets.UTF_8));
        StringBuilder hash = new StringBuilder();
        for (byte b : bytes) hash.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        digest = hash.toString();
    }

    private static Object property(String name, String value) throws Exception {
        return Class.forName("android.os.SystemProperties").getMethod("set", String.class, String.class).invoke(null, name, value);
    }

    private void status(String phase) throws Exception {
        J state = new J().put("version", 1).put("enabled", true).put("phase", phase)
            .put("package", packageName).put("script_sha256", digest).put("injections", injections)
            .put("failures", failures).put("active_targets", sessions.size()).put("connected", attached);
        Path tmp = statusPath.resolveSibling(statusPath.getFileName() + ".tmp");
        Files.write(tmp, (state + "\n").getBytes(StandardCharsets.UTF_8));
        Files.move(tmp, statusPath, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
    }

    private int command(String method, J parameters, String session, int stage) throws Exception {
        int id = ++sequence;
        J message = new J().put("id", id).put("method", method).put("params", parameters);
        if (session != null) message.put("sessionId", session);
        pending.put(id, new Pending(session, method, stage));
        websocket.text(message.toString());
        return id;
    }

    private J autoAttach(boolean root) throws Exception {
        return new J("{\"autoAttach\":true,\"waitForDebuggerOnStart\":true,\"flatten\":true," +
            "\"filter\":[" + (root ? "{\"type\":\"tab\"}" : "{\"type\":\"page\"},{\"type\":\"iframe\"}") +
            ",{\"exclude\":true}]}");
    }

    private void resume(String session) throws Exception {
        command("Runtime.runIfWaitingForDebugger", new J(), session, -1);
    }

    private void failed(Pending request) throws Exception {
        failures++;
        System.err.println("Frame WebXR: " + request.method + " fehlgeschlagen; Seite wird freigegeben.");
        if (request.session == null) throw new IOException("DevTools auto-attach failed");
        if (request.stage < 0) throw new IOException("DevTools could not release the page");
        if (request.stage >= 0) resume(request.session);
        status(attached ? "attached" : "waiting");
    }

    private void handle(J message) throws Exception {
        if (message.has("id")) {
            Pending request = pending.remove(message.number("id"));
            if (request == null) return;
            if (message.has("error")) {
                System.err.println("Frame WebXR: " + request.method + ": " + message.child("error").string("message"));
                failed(request); return;
            }
            if (request.session == null) { attached = true; status("attached"); return; }
            if (request.stage == 0) {
                if (message.child("result").string("identifier").isEmpty()) { failed(request); return; }
                injections++;
                // Enabling Page can initialize the first Android document.
                // Register its hook first; enable still covers later reloads.
                command("Page.enable", new J(), request.session, 1);
            } else if (request.stage == 1) {
                command("Target.setAutoAttach", autoAttach(false), request.session, 2);
            } else if (request.stage == 2) {
                resume(request.session); status("attached");
            }
            return;
        }
        String event = message.string("method");
        J parameters = message.child("params");
        if ("Target.attachedToTarget".equals(event)) {
            String session = parameters.string("sessionId");
            if (session.isEmpty() || !sessions.add(session)) return;
            String type = parameters.child("targetInfo").string("type");
            // Release the tab container while retaining the page's startup
            // pause. Otherwise Android cannot initialize its Page agent.
            if ("tab".equals(type)) command("Target.setAutoAttach", autoAttach(false), session, 2);
            else if ("page".equals(type) || "iframe".equals(type))
                command("Page.addScriptToEvaluateOnNewDocument",
                    new J().put("source", source).put("runImmediately", true), session, 0);
            else resume(session);
        } else if ("Target.detachedFromTarget".equals(event)) {
            String session = parameters.string("sessionId");
            sessions.remove(session);
            pending.entrySet().removeIf(entry -> session.equals(entry.getValue().session));
            status(attached ? "attached" : "waiting");
        }
    }

    private void expired() throws Exception {
        long now = System.nanoTime();
        for (Integer id : new HashSet<>(pending.keySet())) {
            Pending request = pending.get(id);
            if (request != null && now > request.deadline) {
                pending.remove(id);
                if (request.stage >= 0) failed(request);
                else throw new IOException("DevTools resume did not respond");
            }
        }
    }

    // A desktop harness can exercise the real protocol on in-memory streams.
    void serve(FrameDevtools connection) throws Exception {
        websocket = connection; attached = false; pending.clear(); sessions.clear();
        command("Target.setAutoAttach", autoAttach(true), null, 0);
        while (true) {
            try { handle(new J(websocket.receive())); }
            catch (SocketTimeoutException idle) { /* inspect pending command deadlines */ }
            expired();
        }
    }

    private String socketName() throws Exception {
        Set<String> names = new HashSet<>();
        for (String line : Files.readAllLines(Paths.get("/proc/net/unix"), StandardCharsets.US_ASCII)) {
            String[] fields = line.trim().split("\\s+");
            String name = fields[fields.length - 1];
            if ("@chrome_devtools_remote".equals(name)) names.add(name.substring(1));
            else if (name.matches("@chrome_devtools_remote_[0-9]+")) {
                String pid = name.substring(name.lastIndexOf('_') + 1);
                try {
                    String command = new String(Files.readAllBytes(Paths.get("/proc/" + pid + "/cmdline")), StandardCharsets.UTF_8);
                    if (command.equals(packageName + "\0") || command.startsWith(packageName + "\0")) names.add(name.substring(1));
                } catch (IOException gone) { /* browser restarted */ }
            }
        }
        if (names.size() != 1) throw new IOException("Browser socket not ready");
        return names.iterator().next();
    }

    void run() throws Exception {
        Thread.currentThread().setName("frame-webxr");
        status("waiting");
        property("frame.webxr.pid", String.valueOf(Class.forName("android.os.Process").getMethod("myPid").invoke(null)));
        property("frame.webxr.package", packageName);
        long lastNotice = 0;
        while (true) {
            try {
                String name = socketName();
                J version;
                try (FrameDevtools http = FrameDevtools.open(name)) { version = new J(http.version()); }
                if (!packageName.equals(version.string("Android-Package"))) throw new IOException("Different browser package");
                try (FrameDevtools connection = FrameDevtools.open(name)) {
                    connection.upgrade(version.string("webSocketDebuggerUrl"));
                    serve(connection);
                }
            } catch (Exception error) {
                attached = false; pending.clear(); sessions.clear(); status("waiting");
                if (System.nanoTime() - lastNotice > 30_000_000_000L) {
                    System.err.println("Frame WebXR: wartet auf den Android-Browser (" +
                        error.getClass().getSimpleName() + ": " + error.getMessage() + ").");
                    lastNotice = System.nanoTime();
                }
            }
            Thread.sleep(100);
        }
    }

    public static void main(String[] args) {
        try {
            if (args.length != 2 || !("com.android.chrome".equals(args[0]) || "org.chromium.chrome".equals(args[0])))
                throw new IllegalArgumentException("Browser package and script path required");
            Path lockPath = Paths.get("/data/local/tmp/frame-webxr.lock");
            try (FileChannel channel = FileChannel.open(lockPath, StandardOpenOption.CREATE, StandardOpenOption.WRITE);
                 FileLock lock = channel.tryLock()) {
                if (lock == null) return;
                new FrameBrowserXR(args[0], new String(Files.readAllBytes(Paths.get(args[1])), StandardCharsets.UTF_8)).run();
            }
        } catch (Throwable error) {
            error.printStackTrace(); System.exit(1);
        }
    }
}
