package uz.agetai.app;

import android.Manifest;
import android.app.Activity;
import android.content.pm.PackageManager;
import android.media.MediaRecorder;
import android.webkit.JavascriptInterface;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * aget_ai telefon ilovasi.
 * Kompyuterdagi aget_ai dasturiga (server) ulanadi va uning chat sahifasini ko'rsatadi.
 */
public class MainActivity extends Activity {
    private static final int FILE_REQUEST = 1;

    private SharedPreferences prefs;
    private WebView web;
    private ValueCallback<Uri[]> fileCallback;
    private String serverAddr, serverCode;
    private MediaRecorder recorder;
    private File voiceFile;

    /** Chat sahifasidan chaqiriladi: telefon mikrofoni orqali ovozli xabar yozish. */
    public class VoiceBridge {
        @JavascriptInterface
        public boolean startVoice() {
            if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                runOnUiThread(() -> requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, 2));
                return false;
            }
            try {
                voiceFile = new File(getCacheDir(), "ovoz.m4a");
                recorder = new MediaRecorder();
                recorder.setAudioSource(MediaRecorder.AudioSource.MIC);
                recorder.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4);
                recorder.setAudioEncoder(MediaRecorder.AudioEncoder.AAC);
                recorder.setAudioSamplingRate(44100);
                recorder.setAudioEncodingBitRate(96000);
                recorder.setOutputFile(voiceFile.getAbsolutePath());
                recorder.prepare();
                recorder.start();
                return true;
            } catch (Exception e) {
                releaseRecorder();
                return false;
            }
        }

        @JavascriptInterface
        public void stopVoice() {
            boolean ok = true;
            try {
                recorder.stop();
            } catch (Exception e) {
                ok = false;  // juda qisqa yozuv
            }
            releaseRecorder();
            if (!ok) {
                sendToPage("{\"error\":\"Yozuv juda qisqa, qayta urinib ko'ring\"}");
                return;
            }
            new Thread(() -> sendToPage(uploadVoice())).start();
        }
    }

    private void releaseRecorder() {
        if (recorder != null) {
            try { recorder.release(); } catch (Exception ignored) { }
            recorder = null;
        }
    }

    private String uploadVoice() {
        try {
            byte[] data;
            try (InputStream in = new FileInputStream(voiceFile)) {
                ByteArrayOutputStream buf = new ByteArrayOutputStream();
                byte[] chunk = new byte[16384];
                int n;
                while ((n = in.read(chunk)) > 0) buf.write(chunk, 0, n);
                data = buf.toByteArray();
            }
            HttpURLConnection c = (HttpURLConnection) new URL("http://" + serverAddr + "/api/voice").openConnection();
            c.setRequestMethod("POST");
            c.setDoOutput(true);
            c.setConnectTimeout(10000);
            c.setReadTimeout(120000);
            c.setRequestProperty("X-Token", serverCode);
            c.setRequestProperty("X-Filename", "ovoz.m4a");
            c.setRequestProperty("Content-Type", "audio/mp4");
            c.setFixedLengthStreamingMode(data.length);
            try (OutputStream out = c.getOutputStream()) { out.write(data); }
            InputStream in = c.getResponseCode() < 400 ? c.getInputStream() : c.getErrorStream();
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            byte[] chunk = new byte[4096];
            int n;
            while (in != null && (n = in.read(chunk)) > 0) buf.write(chunk, 0, n);
            return buf.toString("UTF-8");
        } catch (Exception e) {
            return "{\"error\":\"Ovozni yuborib bo'lmadi\"}";
        }
    }

    private void sendToPage(String json) {
        runOnUiThread(() -> {
            if (web != null) web.evaluateJavascript("onVoiceResult(" + JSONObject.quote(json) + ")", null);
        });
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences("aget_ai", MODE_PRIVATE);
        String addr = prefs.getString("addr", "");
        String code = prefs.getString("code", "");
        if (addr.isEmpty() || code.isEmpty()) {
            showSetup(null);
        } else {
            showWeb(addr, code);
        }
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    /** Birinchi ekran: kompyuter manzili va kodini kiritish. */
    private void showSetup(String error) {
        if (web != null) {
            web.destroy();
            web = null;
        }
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(24), dp(48), dp(24), dp(24));
        box.setBackgroundColor(Color.WHITE);

        TextView title = new TextView(this);
        title.setText("aget_ai");
        title.setTextSize(28);
        title.setTextColor(Color.parseColor("#1d2330"));
        box.addView(title);

        TextView hint = new TextView(this);
        hint.setText("Kompyuterdagi aget_ai dasturida \"Telefon\" menyusini oching va u yerdagi "
                + "manzil hamda kodni kiriting. Telefon kompyuter bilan bitta Wi-Fi'da bo'lsin.");
        hint.setTextSize(15);
        hint.setTextColor(Color.parseColor("#6b7385"));
        hint.setPadding(0, dp(8), 0, dp(24));
        box.addView(hint);

        if (error != null) {
            TextView err = new TextView(this);
            err.setText(error);
            err.setTextColor(Color.parseColor("#b00020"));
            err.setPadding(0, 0, 0, dp(16));
            box.addView(err);
        }

        final EditText addr = new EditText(this);
        addr.setHint("Manzil, masalan: 192.168.1.5:8765");
        addr.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        addr.setText(prefs.getString("addr", ""));
        box.addView(addr);

        final EditText code = new EditText(this);
        code.setHint("Kod, masalan: 9F3A1C0B");
        code.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS);
        code.setText(prefs.getString("code", ""));
        box.addView(code);

        Button go = new Button(this);
        go.setText("Ulanish");
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(16);
        go.setLayoutParams(lp);
        go.setOnClickListener(v -> {
            String a = addr.getText().toString().trim()
                    .replace("http://", "").replace("https://", "");
            if (a.endsWith("/")) a = a.substring(0, a.length() - 1);
            if (!a.isEmpty() && !a.contains(":")) a = a + ":8765";
            String c = code.getText().toString().trim().toUpperCase();
            if (a.isEmpty() || c.isEmpty()) {
                showSetup("Manzil va kodni kiriting.");
                return;
            }
            prefs.edit().putString("addr", a).putString("code", c).apply();
            showWeb(a, c);
        });
        box.addView(go);
        box.setGravity(Gravity.TOP);
        setContentView(box);
    }

    /** Asosiy ekran: kompyuterdagi chat sahifasi. */
    private void showWeb(String addr, String code) {
        serverAddr = addr;
        serverCode = code;
        web = new WebView(this);
        web.addJavascriptInterface(new VoiceBridge(), "AgetAndroid");
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) {
                    showSetup("Kompyuterga ulanib bo'lmadi (" + addr + "). Kompyuter yoqilgan, "
                            + "aget_ai ochiq va telefon bitta Wi-Fi'da ekanini tekshiring.");
                }
            }
        });

        // Fayl tanlash (rasm, ovozli xabar) uchun
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                             FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                try {
                    startActivityForResult(params.createIntent(), FILE_REQUEST);
                } catch (Exception e) {
                    fileCallback = null;
                    return false;
                }
                return true;
            }
        });

        setContentView(web);
        web.loadUrl("http://" + addr + "/?token=" + Uri.encode(code));
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == FILE_REQUEST && fileCallback != null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(resultCode, data));
            fileCallback = null;
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else if (web != null) {
            // Orqaga tugmasi: ulanish sozlamalariga qaytish
            showSetup(null);
        } else {
            super.onBackPressed();
        }
    }
}
