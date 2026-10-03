/* SPDX-License-Identifier: MIT */
import java.nio.charset.StandardCharsets;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;

/** Set only Chromium's VR default while the browser is stopped. */
public final class FrameBrowserPrefs {
    private static boolean supportedPackage(String name) {
        return "org.chromium.chrome".equals(name) || "com.android.chrome".equals(name);
    }

    // Android supplies org.json. Reflection keeps the helper build independent
    // of an Android SDK, just like FrameRestrictions.
    private static Object object(Class<?> json, Object parent, String key) throws Exception {
        Object value = json.getMethod("optJSONObject", String.class).invoke(parent, key);
        if (value == null) {
            if ((Boolean) json.getMethod("has", String.class).invoke(parent, key)) {
                throw new IllegalArgumentException("Preferences: " + key + " ist kein JSON-Objekt");
            }
            value = json.getConstructor().newInstance();
            json.getMethod("put", String.class, Object.class).invoke(parent, key, value);
        }
        return value;
    }

    public static void update(Path path, boolean allow) throws Exception {
        Class<?> json = Class.forName("org.json.JSONObject");
        byte[] original = Files.exists(path) ? Files.readAllBytes(path) : null;
        Object prefs = json.getConstructor(String.class).newInstance(original == null
            ? "{}" : new String(original, StandardCharsets.UTF_8));
        Object profile = object(json, prefs, "profile");
        Object defaults = object(json, profile, "default_content_setting_values");
        json.getMethod("put", String.class, Object.class).invoke(defaults, "vr", allow ? 1 : 3);
        byte[] updated = (prefs.toString() + "\n").getBytes(StandardCharsets.UTF_8);

        Files.createDirectories(path.getParent());
        Path backup = path.resolveSibling(path.getFileName() + ".frame-vr-backup");
        if (original != null && !Files.exists(backup)) {
            Files.copy(path, backup, StandardCopyOption.COPY_ATTRIBUTES);
        }
        Path temporary = Files.createTempFile(path.getParent(), ".frame-vr-", ".tmp");
        try {
            Files.setPosixFilePermissions(temporary, Files.exists(path)
                ? Files.getPosixFilePermissions(path) : PosixFilePermissions.fromString("rw-------"));
            Files.write(temporary, updated);
            try (FileChannel channel = FileChannel.open(temporary, StandardOpenOption.WRITE)) {
                channel.force(true);
            }
            Files.move(temporary, path, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } finally {
            Files.deleteIfExists(temporary);
        }
    }

    public static void main(String[] args) {
        try {
            if (args.length != 2 || !supportedPackage(args[0])
                || !("allow".equals(args[1]) || "ask".equals(args[1]))) {
                throw new IllegalArgumentException("Frame: Chromium-Paket und VR-Modus allow/ask erforderlich");
            }
            update(Paths.get("/data/data/" + args[0] + "/app_chrome/Default/Preferences"),
                   "allow".equals(args[1]));
            System.out.println("Frame: VR-Berechtigung " + args[1]);
        } catch (Throwable error) {
            error.printStackTrace();
            System.exit(1);
        }
    }
}
