/* SPDX-License-Identifier: MIT */
import java.io.ByteArrayOutputStream;
import java.io.Closeable;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;

/** Minimal HTTP/WebSocket client on Android's existing local DevTools socket. */
public final class FrameDevtools implements Closeable {
    private final Object socket;
    final InputStream input;
    private final OutputStream output;
    private final SecureRandom random = new SecureRandom();
    private static final int LIMIT = 4 * 1024 * 1024;

    private FrameDevtools(Object socket, InputStream input, OutputStream output) {
        this.socket = socket; this.input = input; this.output = output;
    }

    static FrameDevtools open(String name) throws Exception {
        Class<?> type = Class.forName("android.net.LocalSocket");
        Class<?> address = Class.forName("android.net.LocalSocketAddress");
        Class<?> namespace = Class.forName("android.net.LocalSocketAddress$Namespace");
        Object connection = type.getConstructor().newInstance();
        try {
            Object endpoint = address.getConstructor(String.class, namespace)
                .newInstance(name, namespace.getField("ABSTRACT").get(null));
            type.getMethod("connect", address).invoke(connection, endpoint);
            type.getMethod("setSoTimeout", int.class).invoke(connection, 2000);
            return new FrameDevtools(connection,
                (InputStream) type.getMethod("getInputStream").invoke(connection),
                (OutputStream) type.getMethod("getOutputStream").invoke(connection));
        } catch (Exception error) {
            type.getMethod("close").invoke(connection);
            throw error;
        }
    }

    // Also usable by the desktop protocol tests without an Android SDK.
    FrameDevtools(InputStream input, OutputStream output) {
        this(null, input, output);
    }

    private String line() throws IOException {
        ByteArrayOutputStream value = new ByteArrayOutputStream();
        while (true) {
            int next = input.read();
            if (next < 0) throw new EOFException();
            if (next == '\n') break;
            if (next != '\r') value.write(next);
            if (value.size() > 16384) throw new IOException("DevTools HTTP header too large");
        }
        return new String(value.toByteArray(), StandardCharsets.US_ASCII);
    }

    private Map<String, String> headers() throws IOException {
        Map<String, String> headers = new LinkedHashMap<>();
        for (int count = 0; count < 100; count++) {
            String line = line();
            if (line.isEmpty()) return headers;
            int separator = line.indexOf(':');
            if (separator <= 0) throw new IOException("Invalid DevTools header");
            headers.put(line.substring(0, separator).trim().toLowerCase(java.util.Locale.ROOT),
                line.substring(separator + 1).trim());
        }
        throw new IOException("Too many DevTools headers");
    }

    String version() throws IOException {
        output.write(("GET /json/version HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
            .getBytes(StandardCharsets.US_ASCII));
        output.flush();
        if (!line().matches("HTTP/1\\.[01] 200(?: .*|)$")) throw new IOException("DevTools version failed");
        Map<String, String> headers = headers();
        int length = Integer.parseInt(headers.getOrDefault("content-length", "-1"));
        if (length < 0 || length > 262144) throw new IOException("Invalid DevTools response length");
        return new String(readBytes(length), StandardCharsets.UTF_8);
    }

    void upgrade(String debuggerUrl) throws Exception {
        URI uri = new URI(debuggerUrl);
        String path = uri.getRawPath();
        if (!"ws".equals(uri.getScheme()) || path == null ||
            !(path.equals("/devtools/browser") || path.startsWith("/devtools/browser/")) || uri.getRawQuery() != null) {
            throw new IOException("Invalid browser DevTools path");
        }
        byte[] nonce = new byte[16]; random.nextBytes(nonce);
        String key = Base64.getEncoder().encodeToString(nonce);
        String request = "GET " + path + " HTTP/1.1\r\nHost: localhost\r\n" +
            "Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\n" +
            "Sec-WebSocket-Key: " + key + "\r\n\r\n";
        output.write(request.getBytes(StandardCharsets.US_ASCII)); output.flush();
        if (!line().matches("HTTP/1\\.[01] 101(?: .*|)$")) throw new IOException("DevTools WebSocket refused");
        Map<String, String> headers = headers();
        String accept = Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-1")
            .digest((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").getBytes(StandardCharsets.US_ASCII)));
        if (!accept.equals(headers.get("sec-websocket-accept"))) throw new IOException("Invalid WebSocket handshake");
    }

    private int readByte() throws IOException {
        int value = input.read();
        if (value < 0) throw new EOFException();
        return value;
    }

    private byte[] readBytes(int length) throws IOException {
        byte[] value = new byte[length];
        for (int offset = 0; offset < length;) {
            int count = input.read(value, offset, length - offset);
            if (count < 0) throw new EOFException();
            offset += count;
        }
        return value;
    }

    synchronized void send(int opcode, byte[] payload) throws IOException {
        if (payload.length > LIMIT) throw new IOException("DevTools message too large");
        output.write(0x80 | opcode);
        if (payload.length < 126) output.write(0x80 | payload.length);
        else if (payload.length <= 65535) {
            output.write(0x80 | 126); output.write(payload.length >> 8); output.write(payload.length);
        } else {
            output.write(0x80 | 127);
            for (int shift = 56; shift >= 0; shift -= 8) output.write((int) ((long) payload.length >> shift) & 255);
        }
        byte[] mask = new byte[4]; random.nextBytes(mask); output.write(mask);
        byte[] masked = payload.clone();
        for (int i = 0; i < masked.length; i++) masked[i] ^= mask[i % 4];
        output.write(masked); output.flush();
    }

    void text(String message) throws IOException { send(1, message.getBytes(StandardCharsets.UTF_8)); }

    String receive() throws IOException {
        ByteArrayOutputStream text = new ByteArrayOutputStream();
        boolean continuing = false;
        boolean frameStarted = false;
        try {
        while (true) {
            int first = readByte();
            frameStarted = true;
            int second = readByte();
            boolean fin = (first & 128) != 0;
            int opcode = first & 15;
            if ((first & 112) != 0 || (second & 128) != 0) throw new IOException("Invalid server WebSocket frame");
            long length = second & 127;
            if (length == 126) length = ((long) readByte() << 8) | readByte();
            else if (length == 127) {
                length = 0;
                for (int i = 0; i < 8; i++) length = (length << 8) | readByte();
            }
            if (length < 0 || length > LIMIT || (opcode >= 8 && (!fin || length > 125)))
                throw new IOException("Invalid WebSocket payload length");
            byte[] payload = readBytes((int) length);
            if (opcode == 8) throw new EOFException("DevTools closed");
            if (opcode == 9) { send(10, payload); frameStarted = false; continue; }
            if (opcode == 10) { frameStarted = false; continue; }
            if ((opcode == 1 && continuing) || (opcode == 0 && !continuing) || (opcode != 0 && opcode != 1))
                throw new IOException("Invalid DevTools text frame");
            if (text.size() + payload.length > LIMIT) throw new IOException("DevTools message too large");
            text.write(payload); continuing = true;
            if (fin) return new String(text.toByteArray(), StandardCharsets.UTF_8);
        }
        } catch (IOException error) {
            // Android LocalSocket reports SO_RCVTIMEO as IOException(EAGAIN),
            // unlike java.net.Socket's SocketTimeoutException. Only an idle
            // read can be resumed; a partially consumed frame must reconnect.
            boolean timeout = error instanceof SocketTimeoutException ||
                (socket != null && "Try again".equals(error.getMessage()));
            if (!timeout) throw error;
            if (frameStarted || continuing) throw new IOException("Incomplete WebSocket frame", error);
            if (error instanceof SocketTimeoutException) throw error;
            SocketTimeoutException idle = new SocketTimeoutException("Idle Android DevTools socket");
            idle.initCause(error);
            throw idle;
        }
    }

    public void close() throws IOException {
        if (socket != null) {
            try { socket.getClass().getMethod("close").invoke(socket); }
            catch (Exception error) { throw new IOException(error); }
        } else { input.close(); output.close(); }
    }
}
