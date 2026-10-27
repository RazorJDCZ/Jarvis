package com.juandi.jarvis;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaPlayer;
import android.media.MediaRecorder;
import android.os.IBinder;
import android.util.Log;
import android.webkit.CookieManager;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.DataOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URI;
import java.net.URL;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

public final class AmbientVoiceService extends Service {
    private static final String LOG_TAG = "JarvisAmbient";
    private static final String CHANNEL = "jarvis_ambient_voice";
    private static final int NOTIFICATION = 41;
    private static final String ACTION_START = "com.juandi.jarvis.START_AMBIENT";
    private static final String ACTION_STOP = "com.juandi.jarvis.STOP_AMBIENT";
    private static final String EXTRA_URL = "server_url";
    private static final int SAMPLE_RATE = 16_000;
    private static final int CHUNK_SAMPLES = 320;
    private static final int MAX_CHUNKS = 900;
    private static final AtomicBoolean RUNNING = new AtomicBoolean(false);

    private final AtomicBoolean stopRequested = new AtomicBoolean(false);
    private Thread worker;
    private AudioRecord recorder;
    private String baseUrl;

    public static boolean isRunning() {
        return RUNNING.get();
    }

    public static void start(Context context, String url) {
        Intent intent = new Intent(context, AmbientVoiceService.class)
                .setAction(ACTION_START)
                .putExtra(EXTRA_URL, url);
        context.startForegroundService(intent);
    }

    public static void stop(Context context) {
        context.startService(new Intent(context, AmbientVoiceService.class).setAction(ACTION_STOP));
    }

    @Override
    public void onCreate() {
        super.onCreate();
        NotificationChannel channel = new NotificationChannel(
                CHANNEL,
                getString(R.string.ambient_channel),
                NotificationManager.IMPORTANCE_LOW);
        channel.setDescription(getString(R.string.ambient_description));
        getSystemService(NotificationManager.class).createNotificationChannel(channel);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_STOP.equals(intent.getAction())) {
            stopAmbient();
            return START_NOT_STICKY;
        }
        if (intent == null || !ACTION_START.equals(intent.getAction())) return START_NOT_STICKY;
        baseUrl = intent.getStringExtra(EXTRA_URL);
        if (baseUrl == null || !baseUrl.startsWith("https://")) {
            stopSelf();
            return START_NOT_STICKY;
        }
        startForeground(NOTIFICATION, notification("Escuchando solo cuando digas Jarvis"));
        if (RUNNING.compareAndSet(false, true)) {
            stopRequested.set(false);
            worker = new Thread(this::recordLoop, "jarvis-ambient-microphone");
            worker.start();
        }
        return START_NOT_STICKY;
    }

    private Notification notification(String status) {
        Intent openIntent = new Intent(this, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent open = PendingIntent.getActivity(
                this, 1, openIntent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop = PendingIntent.getService(
                this,
                2,
                new Intent(this, AmbientVoiceService.class).setAction(ACTION_STOP),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_jarvis)
                .setContentTitle("Jarvis // voz ambiental")
                .setContentText(status)
                .setContentIntent(open)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .addAction(new Notification.Action.Builder(null, "Detener", stop).build())
                .build();
    }

    private void updateNotification(String status) {
        getSystemService(NotificationManager.class).notify(NOTIFICATION, notification(status));
    }

    private void recordLoop() {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            updateNotification("Falta permiso de micrófono");
            stopAmbient();
            return;
        }
        int minimum = AudioRecord.getMinBufferSize(
                SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
        int bufferSize = Math.max(minimum, CHUNK_SAMPLES * 8);
        recorder = new AudioRecord(
                MediaRecorder.AudioSource.VOICE_RECOGNITION,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufferSize);
        if (recorder.getState() != AudioRecord.STATE_INITIALIZED) {
            updateNotification("No pude iniciar el micrófono");
            stopAmbient();
            return;
        }
        Deque<short[]> preRoll = new ArrayDeque<>();
        List<short[]> phrase = new ArrayList<>();
        int silenceChunks = 0;
        double threshold = calibrate(recorder);
        try {
            recorder.startRecording();
            while (!stopRequested.get()) {
                short[] chunk = new short[CHUNK_SAMPLES];
                int read = recorder.read(chunk, 0, chunk.length);
                if (read <= 0) continue;
                if (read != chunk.length) {
                    short[] compact = new short[read];
                    System.arraycopy(chunk, 0, compact, 0, read);
                    chunk = compact;
                }
                double level = rms(chunk);
                if (phrase.isEmpty()) {
                    preRoll.addLast(chunk);
                    while (preRoll.size() > 22) preRoll.removeFirst();
                    if (level >= threshold) {
                        phrase.addAll(preRoll);
                        preRoll.clear();
                        silenceChunks = 0;
                        updateNotification("Te escucho…");
                    }
                    continue;
                }
                phrase.add(chunk);
                silenceChunks = level < threshold * 0.72 ? silenceChunks + 1 : 0;
                if ((phrase.size() > 20 && silenceChunks >= 45) || phrase.size() >= MAX_CHUNKS) {
                    byte[] wav = wav(phrase);
                    phrase.clear();
                    preRoll.clear();
                    silenceChunks = 0;
                    recorder.stop();
                    String nextStatus = handleUtterance(wav);
                    if (nextStatus == null) {
                        stopRequested.set(true);
                        break;
                    }
                    if (!stopRequested.get()) {
                        recorder.startRecording();
                        updateNotification(nextStatus);
                    }
                }
            }
        } catch (RuntimeException error) {
            if (!stopRequested.get()) {
                Log.e(LOG_TAG, "Ambient microphone interrupted", error);
                updateNotification("El micrófono se interrumpió");
            }
        } finally {
            releaseRecorder();
            RUNNING.set(false);
            stopForeground(STOP_FOREGROUND_REMOVE);
            stopSelf();
        }
    }

    private double calibrate(AudioRecord audioRecord) {
        audioRecord.startRecording();
        double total = 0;
        int samples = 0;
        for (int index = 0; index < 35 && !stopRequested.get(); index++) {
            short[] chunk = new short[CHUNK_SAMPLES];
            int read = audioRecord.read(chunk, 0, chunk.length);
            if (read > 0) {
                total += rms(chunk);
                samples++;
            }
        }
        audioRecord.stop();
        double noise = samples == 0 ? 250 : total / samples;
        return Math.max(650, Math.min(6000, noise * 3.4));
    }

    private double rms(short[] values) {
        double total = 0;
        for (short value : values) total += (double) value * value;
        return Math.sqrt(total / Math.max(1, values.length));
    }

    private byte[] wav(List<short[]> chunks) {
        int sampleCount = chunks.stream().mapToInt(value -> value.length).sum();
        int dataSize = sampleCount * 2;
        ByteBuffer output = ByteBuffer.allocate(44 + dataSize).order(ByteOrder.LITTLE_ENDIAN);
        output.put("RIFF".getBytes(StandardCharsets.US_ASCII));
        output.putInt(36 + dataSize);
        output.put("WAVEfmt ".getBytes(StandardCharsets.US_ASCII));
        output.putInt(16);
        output.putShort((short) 1);
        output.putShort((short) 1);
        output.putInt(SAMPLE_RATE);
        output.putInt(SAMPLE_RATE * 2);
        output.putShort((short) 2);
        output.putShort((short) 16);
        output.put("data".getBytes(StandardCharsets.US_ASCII));
        output.putInt(dataSize);
        for (short[] chunk : chunks) for (short sample : chunk) output.putShort(sample);
        return output.array();
    }

    private String handleUtterance(byte[] audio) {
        updateNotification("Procesando con Jarvis…");
        try {
            JSONObject done = sendVoice(audio);
            if (done == null) return "No recibí una respuesta completa; sigo atento";
            if (!done.optBoolean("accepted", false)) {
                return "No escuché Jarvis; sigo atento";
            }
            String answer = done.optString("response", "").trim();
            if (!answer.isEmpty()) {
                updateNotification(answer.length() > 110 ? answer.substring(0, 107) + "…" : answer);
                playNeuralVoice(answer);
            } else if (done.optBoolean("needs_command", false)) {
                return "Te escucho; di ahora la instrucción";
            }
            return "Escuchando solo cuando digas Jarvis";
        } catch (VoiceRequestException error) {
            Log.w(LOG_TAG, "Ambient voice request rejected with HTTP " + error.statusCode);
            if (error.statusCode == 401 || error.statusCode == 403) {
                showProblemNotification("Sesión bloqueada", "Abre Jarvis y desbloquéalo con tu biometría");
                return null;
            }
            return "El núcleo rechazó la voz; sigo atento";
        } catch (Exception error) {
            Log.w(LOG_TAG, "Ambient voice request failed", error);
            return "Sin conexión con tu PC; volveré a intentarlo";
        }
    }

    private JSONObject sendVoice(byte[] audio) throws Exception {
        String boundary = "Jarvis" + UUID.randomUUID().toString().replace("-", "");
        HttpURLConnection connection = open("/api/voice/stream", "POST");
        connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
        connection.setChunkedStreamingMode(8192);
        try (DataOutputStream output = new DataOutputStream(connection.getOutputStream())) {
            formField(output, boundary, "session_id", "android-ambient");
            formField(output, boundary, "wake_mode", "true");
            formField(output, boundary, "wake_fast", "false");
            output.writeBytes("--" + boundary + "\r\n");
            output.writeBytes("Content-Disposition: form-data; name=\"audio\"; filename=\"ambient.wav\"\r\n");
            output.writeBytes("Content-Type: audio/wav\r\n\r\n");
            output.write(audio);
            output.writeBytes("\r\n--" + boundary + "--\r\n");
        }
        int statusCode = connection.getResponseCode();
        if (statusCode != 200) {
            connection.disconnect();
            throw new VoiceRequestException(statusCode);
        }
        JSONObject done = null;
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                connection.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                JSONObject event = new JSONObject(line);
                if ("done".equals(event.optString("event"))) done = event;
                if ("error".equals(event.optString("event"))) {
                    throw new IllegalStateException(event.optString("detail"));
                }
            }
        } finally {
            connection.disconnect();
        }
        return done;
    }

    private void formField(DataOutputStream output, String boundary, String name, String value)
            throws Exception {
        output.writeBytes("--" + boundary + "\r\n");
        output.writeBytes("Content-Disposition: form-data; name=\"" + name + "\"\r\n\r\n");
        output.write(value.getBytes(StandardCharsets.UTF_8));
        output.writeBytes("\r\n");
    }

    private void playNeuralVoice(String text) throws Exception {
        HttpURLConnection connection = open("/api/tts", "POST");
        connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
        connection.setDoOutput(true);
        byte[] body = new JSONObject().put("text", text).toString().getBytes(StandardCharsets.UTF_8);
        connection.getOutputStream().write(body);
        if (connection.getResponseCode() != 200) throw new IllegalStateException("HTTP tts");
        File audio = File.createTempFile("jarvis-response-", ".wav", getCacheDir());
        try (InputStream input = connection.getInputStream(); FileOutputStream output = new FileOutputStream(audio)) {
            byte[] buffer = new byte[8192];
            int read;
            while ((read = input.read(buffer)) >= 0) output.write(buffer, 0, read);
        } finally {
            connection.disconnect();
        }
        CountDownLatch finished = new CountDownLatch(1);
        MediaPlayer player = new MediaPlayer();
        try {
            player.setDataSource(audio.getAbsolutePath());
            player.setOnCompletionListener(value -> finished.countDown());
            player.setOnErrorListener((value, what, extra) -> {
                finished.countDown();
                return true;
            });
            player.prepare();
            player.start();
            finished.await(120, TimeUnit.SECONDS);
        } finally {
            player.release();
            if (!audio.delete()) audio.deleteOnExit();
        }
    }

    private HttpURLConnection open(String path, String method) throws Exception {
        URL endpoint = new URL(baseUrl + path);
        HttpURLConnection connection = (HttpURLConnection) endpoint.openConnection();
        connection.setRequestMethod(method);
        connection.setConnectTimeout(12_000);
        connection.setReadTimeout(180_000);
        connection.setUseCaches(false);
        connection.setDoOutput("POST".equals(method) || "PUT".equals(method) || "PATCH".equals(method));
        connection.setRequestProperty("Accept", "application/json, application/x-ndjson");
        connection.setRequestProperty("Origin", origin());
        String cookie = CookieManager.getInstance().getCookie(baseUrl);
        if (cookie != null && !cookie.trim().isEmpty()) {
            connection.setRequestProperty("Cookie", cookie);
        }
        return connection;
    }

    private String origin() {
        URI uri = URI.create(baseUrl);
        String port = uri.getPort() < 0 ? "" : ":" + uri.getPort();
        return uri.getScheme() + "://" + uri.getHost() + port;
    }

    private void showProblemNotification(String title, String detail) {
        Intent openIntent = new Intent(this, MainActivity.class)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent open = PendingIntent.getActivity(
                this, 3, openIntent, PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification problem = new Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.ic_jarvis)
                .setContentTitle(title)
                .setContentText(detail)
                .setContentIntent(open)
                .setAutoCancel(true)
                .build();
        getSystemService(NotificationManager.class).notify(NOTIFICATION + 1, problem);
    }

    private static final class VoiceRequestException extends Exception {
        private final int statusCode;

        private VoiceRequestException(int statusCode) {
            super("HTTP " + statusCode);
            this.statusCode = statusCode;
        }
    }

    private void stopAmbient() {
        stopRequested.set(true);
        releaseRecorder();
        RUNNING.set(false);
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    private synchronized void releaseRecorder() {
        if (recorder == null) return;
        try {
            recorder.stop();
        } catch (RuntimeException ignored) {
            // It may already have been stopped while Jarvis produced a response.
        }
        recorder.release();
        recorder = null;
    }

    @Override
    public void onDestroy() {
        stopRequested.set(true);
        releaseRecorder();
        RUNNING.set(false);
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
