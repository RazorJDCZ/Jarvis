package com.juandi.jarvis;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.res.ColorStateList;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.util.Log;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.window.OnBackInvokedCallback;
import android.window.OnBackInvokedDispatcher;
import android.webkit.CookieManager;
import android.webkit.ConsoleMessage;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.ImageButton;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.PopupWindow;
import android.widget.TextView;
import android.widget.Toast;

import androidx.webkit.WebSettingsCompat;
import androidx.webkit.WebViewFeature;

import java.net.URI;
import java.util.Locale;

public final class MainActivity extends Activity {
    private static final String LOG_TAG = "JarvisMobile";
    private static final int AUDIO_PERMISSION = 20;
    private static final int NOTIFICATION_PERMISSION = 21;
    private static final int FILE_CHOOSER = 22;
    private static final int CAMERA_PERMISSION = 23;
    private static final String PREFS = "jarvis_mobile";
    private static final String URL_KEY = "server_url";
    private static final String CHAT_VISIBLE_KEY = "chat_visible";

    private WebView webView;
    private ImageButton ambientButton;
    private ImageButton pushToTalkButton;
    private ImageButton chatButton;
    private TextView connectionStatus;
    private ValueCallback<Uri[]> fileCallback;
    private OnBackInvokedCallback backCallback;
    private boolean openControlDeckAfterLoad;
    private boolean pushToTalkPressed;
    private boolean startPushToTalkAfterLoad;
    private boolean ambientPermissionPending;
    private boolean webConnectionReady;
    private boolean pendingVoiceSubmit;
    private String webConnectionState = "loading";
    private String voiceState = "idle";
    private int voiceStartGeneration;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setStatusBarColor(Color.rgb(7, 10, 18));
        getWindow().setNavigationBarColor(Color.rgb(7, 10, 18));
        setContentView(buildInterface());
        configureWebView();
        if (android.os.Build.VERSION.SDK_INT >= 33) {
            backCallback = this::handleBack;
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(
                    OnBackInvokedDispatcher.PRIORITY_DEFAULT, backCallback);
        }
        requestNotificationPermission();
        String url = configuredUrl();
        if (url.isEmpty()) {
            showServerDialog(false);
        } else {
            webView.loadUrl(url);
        }
    }

    private View buildInterface() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.rgb(7, 10, 18));
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(
                    0,
                    insets.getSystemWindowInsetTop(),
                    0,
                    insets.getSystemWindowInsetBottom());
            return insets;
        });

        LinearLayout bar = new LinearLayout(this);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setMinimumHeight(dp(58));
        bar.setPadding(dp(15), dp(5), dp(6), dp(5));
        bar.setBackgroundColor(Color.rgb(10, 8, 17));
        bar.setElevation(dp(8));

        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.ic_jarvis);
        logo.setContentDescription(null);
        LinearLayout.LayoutParams logoParams = new LinearLayout.LayoutParams(dp(34), dp(34));
        logoParams.setMarginEnd(dp(12));
        bar.addView(logo, logoParams);

        LinearLayout titleBlock = new LinearLayout(this);
        titleBlock.setOrientation(LinearLayout.VERTICAL);
        titleBlock.setGravity(Gravity.CENTER_VERTICAL);

        TextView brand = new TextView(this);
        brand.setText("JARVIS");
        brand.setTextColor(Color.rgb(255, 241, 245));
        brand.setTextSize(16);
        brand.setLetterSpacing(0.18f);
        titleBlock.addView(brand);

        connectionStatus = new TextView(this);
        connectionStatus.setText("ENLACE PRIVADO");
        connectionStatus.setTextColor(Color.rgb(93, 243, 189));
        connectionStatus.setTextSize(8);
        connectionStatus.setLetterSpacing(0.12f);
        titleBlock.addView(connectionStatus);
        bar.addView(titleBlock, new LinearLayout.LayoutParams(0, dp(48), 1));

        ambientButton = appBarButton(R.drawable.ic_ambient, "Activar voz ambiental");
        ambientButton.setOnClickListener(view -> toggleAmbient());
        bar.addView(ambientButton);

        pushToTalkButton = appBarButton(R.drawable.ic_mic_hold, "Mantener pulsado para hablar");
        pushToTalkButton.setOnClickListener(view -> { });
        pushToTalkButton.setOnTouchListener(this::handlePushToTalkTouch);
        bar.addView(pushToTalkButton);

        chatButton = appBarButton(R.drawable.ic_chat, "Mostrar conversación");
        chatButton.setOnClickListener(view -> toggleChatPanel());
        bar.addView(chatButton);

        ImageButton menuButton = appBarButton(R.drawable.ic_menu, "Abrir menú de Jarvis");
        menuButton.setOnClickListener(this::showAppMenu);
        bar.addView(menuButton);

        webView = new WebView(this);
        webView.setBackgroundColor(Color.rgb(7, 10, 18));
        root.addView(bar, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(webView, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        return root;
    }

    private ImageButton appBarButton(int icon, String description) {
        ImageButton button = new ImageButton(this);
        button.setImageResource(icon);
        button.setImageTintList(ColorStateList.valueOf(Color.rgb(238, 211, 220)));
        button.setContentDescription(description);
        button.setPadding(dp(11), dp(11), dp(11), dp(11));
        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.rgb(28, 13, 25));
        background.setStroke(dp(1), Color.rgb(80, 29, 49));
        background.setCornerRadius(dp(12));
        button.setBackground(background);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(dp(44), dp(44));
        params.setMargins(dp(6), 0, 0, 0);
        button.setLayoutParams(params);
        return button;
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void configureWebView() {
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        String userAgent = settings.getUserAgentString();
        if (userAgent == null || !userAgent.contains("JarvisAndroid/")) {
            settings.setUserAgentString(
                    (userAgent == null ? "" : userAgent + " ")
                            + "JarvisAndroid/" + BuildConfig.VERSION_NAME);
        }
        if (WebViewFeature.isFeatureSupported(WebViewFeature.WEB_AUTHENTICATION)) {
            WebSettingsCompat.setWebAuthenticationSupport(
                    settings,
                    WebSettingsCompat.WEB_AUTHENTICATION_SUPPORT_FOR_APP);
            Log.i(LOG_TAG, "WebAuthn support enabled: "
                    + WebSettingsCompat.getWebAuthenticationSupport(settings));
        } else {
            Log.e(LOG_TAG, "This Android WebView does not support WebAuthn");
        }
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, false);
        webView.addJavascriptInterface(new NativeBridge(), "JarvisNative");
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleNavigation(url);
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return handleNavigation(request.getUrl().toString());
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                applyMobileShell();
                updateAppBarState();
                view.postDelayed(() -> view.evaluateJavascript(
                        "window.jarvisMobileVoice?.syncNativeState?.()",
                        null), 250);
                if (startPushToTalkAfterLoad && pushToTalkPressed && isHomeUrl(url)) {
                    startPushToTalkAfterLoad = false;
                    view.postDelayed(MainActivity.this::startPushToTalk, 200);
                }
                if (openControlDeckAfterLoad && isHomeUrl(url)) {
                    openControlDeckAfterLoad = false;
                    view.postDelayed(() -> view.evaluateJavascript(
                            "document.getElementById('controlDeckCompactButton')?.click()",
                            null), 250);
                }
            }
        });
        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(ConsoleMessage message) {
                if (message.messageLevel() == ConsoleMessage.MessageLevel.ERROR
                        || message.messageLevel() == ConsoleMessage.MessageLevel.WARNING) {
                    Log.w(
                            LOG_TAG,
                            "WebView " + message.messageLevel() + " at line "
                                    + message.lineNumber() + ": "
                                    + cleanNativeText(message.message(), 240));
                }
                return true;
            }

            @Override
            public void onPermissionRequest(PermissionRequest request) {
                runOnUiThread(() -> {
                    boolean audio = false;
                    boolean camera = false;
                    for (String resource : request.getResources()) {
                        audio |= PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resource);
                        camera |= PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(resource);
                    }
                    if (!sameOrigin(request.getOrigin().toString())) {
                        Log.w(LOG_TAG, "Rejected WebView media permission from another origin");
                        request.deny();
                    } else if (audio && !hasAudioPermission()) {
                        Log.i(LOG_TAG, "Requesting Android microphone permission for WebView");
                        request.deny();
                        requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, AUDIO_PERMISSION);
                    } else if (camera && checkSelfPermission(Manifest.permission.CAMERA)
                            != PackageManager.PERMISSION_GRANTED) {
                        request.deny();
                        requestPermissions(new String[]{Manifest.permission.CAMERA}, CAMERA_PERMISSION);
                    } else {
                        Log.i(LOG_TAG, "Granted same-origin WebView media permission");
                        request.grant(request.getResources());
                    }
                });
            }

            @Override
            public boolean onShowFileChooser(
                    WebView view,
                    ValueCallback<Uri[]> callback,
                    FileChooserParams params
            ) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                try {
                    startActivityForResult(params.createIntent(), FILE_CHOOSER);
                    return true;
                } catch (RuntimeException error) {
                    fileCallback = null;
                    Toast.makeText(MainActivity.this, "No hay selector de archivos disponible", Toast.LENGTH_LONG).show();
                    return false;
                }
            }
        });
    }

    public final class NativeBridge {
        @JavascriptInterface
        public void onConnectionState(String state, String detail) {
            runOnUiThread(() -> handleNativeConnectionState(state, detail));
        }

        @JavascriptInterface
        public void onVoiceState(String state, String detail) {
            runOnUiThread(() -> handleNativeVoiceState(state, detail));
        }
    }

    private void handleNativeConnectionState(String state, String detail) {
        String normalized = cleanNativeText(state, 32).toLowerCase(Locale.ROOT);
        Log.i(LOG_TAG, "Connection state: " + normalized);
        webConnectionState = normalized.isEmpty() ? "offline" : normalized;
        webConnectionReady = "ready".equals(webConnectionState);
        if (webConnectionReady) {
            CookieManager.getInstance().flush();
        } else if ("locked".equals(webConnectionState) || "offline".equals(webConnectionState)) {
            if ("starting".equals(voiceState) || "recording".equals(voiceState)) {
                requestVoiceStop(false);
            }
        }
        updateAppBarState();
        String message = cleanNativeText(detail, 160);
        if (!message.isEmpty() && !webConnectionReady) {
            connectionStatus.setText(message.toUpperCase(Locale.ROOT));
        }
    }

    private void handleNativeVoiceState(String state, String detail) {
        String normalized = cleanNativeText(state, 32).toLowerCase(Locale.ROOT);
        Log.i(LOG_TAG, "Voice state: " + normalized);
        String message = cleanNativeText(detail, 160);
        voiceState = normalized.isEmpty() ? "idle" : normalized;
        if ("recording".equals(voiceState)) {
            connectionStatus.setText("TE ESCUCHO MIENTRAS PULSAS");
            connectionStatus.setTextColor(Color.rgb(255, 54, 88));
            if (!pushToTalkPressed || pendingVoiceSubmit) requestVoiceStop(true);
        } else if ("starting".equals(voiceState)) {
            connectionStatus.setText("ABRIENDO MICRÓFONO…");
            connectionStatus.setTextColor(Color.rgb(255, 54, 88));
        } else if ("processing".equals(voiceState)) {
            pendingVoiceSubmit = false;
            connectionStatus.setText("PROCESANDO VOZ…");
            connectionStatus.setTextColor(Color.rgb(190, 138, 156));
        } else {
            pendingVoiceSubmit = false;
            if ("locked".equals(voiceState)) {
                webConnectionReady = false;
                webConnectionState = "locked";
            }
            if (!message.isEmpty()) {
                connectionStatus.setText(message.toUpperCase(Locale.ROOT));
                connectionStatus.setTextColor(
                        "error".equals(voiceState) || "locked".equals(voiceState)
                                ? Color.rgb(255, 92, 112)
                                : Color.rgb(93, 243, 189));
            }
            if ("too_short".equals(voiceState)) {
                Toast.makeText(this, "Mantén pulsado un poco más para hablar", Toast.LENGTH_SHORT).show();
            } else if ("busy".equals(voiceState)) {
                Toast.makeText(this, "Jarvis todavía está procesando", Toast.LENGTH_SHORT).show();
            } else if ("locked".equals(voiceState)) {
                Toast.makeText(this, "Desbloquea Jarvis con tu biometría", Toast.LENGTH_LONG).show();
            } else if ("error".equals(voiceState) && !message.isEmpty()) {
                Toast.makeText(this, message, Toast.LENGTH_LONG).show();
            }
            voiceState = "idle";
            connectionStatus.postDelayed(this::updateAppBarState, 1400);
        }
        updateVoiceButtons();
    }

    private String cleanNativeText(String value, int maximum) {
        if (value == null) return "";
        String cleaned = value.replace('\r', ' ').replace('\n', ' ').trim();
        return cleaned.substring(0, Math.min(cleaned.length(), maximum));
    }

    private boolean sameOrigin(String candidate) {
        try {
            URI expected = URI.create(configuredUrl());
            URI value = URI.create(candidate);
            return expected.getScheme().equalsIgnoreCase(value.getScheme())
                    && expected.getHost().equalsIgnoreCase(value.getHost())
                    && effectivePort(expected) == effectivePort(value);
        } catch (RuntimeException error) {
            return false;
        }
    }

    private boolean handleNavigation(String url) {
        if (sameOrigin(url)) return false;
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (RuntimeException error) {
            Toast.makeText(this, "No pude abrir ese enlace", Toast.LENGTH_LONG).show();
        }
        return true;
    }

    private void showAppMenu(View anchor) {
        LinearLayout menu = new LinearLayout(this);
        menu.setOrientation(LinearLayout.VERTICAL);
        menu.setPadding(dp(8), dp(12), dp(8), dp(10));
        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.rgb(19, 8, 18));
        background.setStroke(dp(1), Color.rgb(122, 28, 57));
        background.setCornerRadius(dp(18));
        menu.setBackground(background);

        TextView heading = new TextView(this);
        heading.setText("JARVIS  //  ACCESOS");
        heading.setTextColor(Color.rgb(255, 54, 88));
        heading.setTextSize(9);
        heading.setLetterSpacing(0.13f);
        heading.setGravity(Gravity.CENTER_VERTICAL);
        heading.setPadding(dp(14), dp(2), dp(12), dp(10));
        menu.addView(heading, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(38)));

        int popupWidth = Math.min(
                dp(316),
                getResources().getDisplayMetrics().widthPixels - dp(24));
        PopupWindow popup = new PopupWindow(
                menu,
                popupWidth,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                true);
        popup.setBackgroundDrawable(new GradientDrawable());
        popup.setOutsideTouchable(true);
        popup.setElevation(dp(18));

        boolean chatVisible = getSharedPreferences(PREFS, MODE_PRIVATE)
                .getBoolean(CHAT_VISIBLE_KEY, false);
        addMenuItem(menu, "01", "Inicio", () -> loadAppPath(""), popup);
        addMenuItem(menu, "02", "Mi día", () -> loadAppPath("/organizer"), popup);
        addMenuItem(menu, "03", "Correos", () -> loadAppPath("/mail"), popup);
        addMenuItem(menu, "04", "Panel de control", this::openControlDeck, popup);
        addMenuDivider(menu);
        addMenuItem(
                menu,
                "05",
                chatVisible ? "Ocultar conversación" : "Mostrar conversación",
                this::toggleChatPanel,
                popup);
        addMenuItem(
                menu,
                "06",
                AmbientVoiceService.isRunning() ? "Detener voz ambiental" : "Activar voz ambiental",
                this::toggleAmbient,
                popup);
        addMenuItem(menu, "07", "Recargar", webView::reload, popup);
        addMenuItem(menu, "08", "Conexión privada", () -> showServerDialog(true), popup);
        popup.showAsDropDown(anchor, anchor.getWidth() - popupWidth, dp(6));
    }

    private void addMenuItem(
            LinearLayout parent,
            String index,
            String label,
            Runnable action,
            PopupWindow popup
    ) {
        LinearLayout row = new LinearLayout(this);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(dp(12), 0, dp(10), 0);
        row.setContentDescription(label);
        row.setClickable(true);
        row.setFocusable(true);
        GradientDrawable rowBackground = new GradientDrawable();
        rowBackground.setColor(Color.rgb(25, 11, 23));
        rowBackground.setCornerRadius(dp(11));
        row.setBackground(rowBackground);

        TextView number = new TextView(this);
        number.setText(index);
        number.setTextColor(Color.rgb(255, 54, 88));
        number.setTextSize(9);
        number.setLetterSpacing(0.1f);
        row.addView(number, new LinearLayout.LayoutParams(dp(38), dp(50)));
        number.setGravity(Gravity.CENTER_VERTICAL);

        TextView title = new TextView(this);
        title.setText(label);
        title.setTextColor(Color.rgb(255, 235, 241));
        title.setTextSize(14);
        title.setGravity(Gravity.CENTER_VERTICAL);
        row.addView(title, new LinearLayout.LayoutParams(0, dp(50), 1));

        TextView arrow = new TextView(this);
        arrow.setText("›");
        arrow.setTextColor(Color.rgb(79, 129, 255));
        arrow.setTextSize(22);
        arrow.setGravity(Gravity.CENTER);
        row.addView(arrow, new LinearLayout.LayoutParams(dp(28), dp(50)));

        row.setOnClickListener(view -> {
            popup.dismiss();
            action.run();
        });
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(52));
        params.setMargins(0, dp(2), 0, dp(2));
        parent.addView(row, params);
    }

    private void addMenuDivider(LinearLayout parent) {
        View divider = new View(this);
        divider.setBackgroundColor(Color.rgb(74, 24, 43));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(1));
        params.setMargins(dp(12), dp(7), dp(12), dp(7));
        parent.addView(divider, params);
    }

    private void loadAppPath(String path) {
        String baseUrl = configuredUrl();
        if (baseUrl.isEmpty()) {
            showServerDialog(false);
            return;
        }
        connectionStatus.setText("ABRIENDO…");
        connectionStatus.setTextColor(Color.rgb(190, 138, 156));
        webView.loadUrl(baseUrl + path);
    }

    private void openControlDeck() {
        if (!isHomeUrl(webView.getUrl())) {
            openControlDeckAfterLoad = true;
            loadAppPath("");
            return;
        }
        webView.evaluateJavascript(
                "document.getElementById('controlDeckCompactButton')?.click()",
                null);
    }

    private void toggleChatPanel() {
        boolean currentlyVisible = getSharedPreferences(PREFS, MODE_PRIVATE)
                .getBoolean(CHAT_VISIBLE_KEY, false);
        boolean nextVisible = !currentlyVisible;
        getSharedPreferences(PREFS, MODE_PRIVATE)
                .edit()
                .putBoolean(CHAT_VISIBLE_KEY, nextVisible)
                .apply();
        updateChatButton(nextVisible);
        if (!isHomeUrl(webView.getUrl())) {
            if (nextVisible) loadAppPath("");
            return;
        }
        applyMobileShell();
    }

    private void applyMobileShell() {
        boolean chatVisible = getSharedPreferences(PREFS, MODE_PRIVATE)
                .getBoolean(CHAT_VISIBLE_KEY, false);
        String hidden = chatVisible ? "false" : "true";
        webView.evaluateJavascript(
                "(() => {"
                        + "document.documentElement.classList.add('native-android');"
                        + "if (!document.body) return;"
                        + "document.body.classList.toggle('mobile-chat-hidden', "
                        + hidden
                        + ");"
                        + "const panel = document.querySelector('.conversation-panel');"
                        + "panel?.setAttribute('aria-hidden', '" + hidden + "');"
                        + "const title = panel?.querySelector('.panel-heading > div:first-child span');"
                        + "if (title) title.textContent = 'CONVERSACIÓN';"
                        + "})()",
                null);
        updateChatButton(chatVisible);
    }

    private void updateChatButton(boolean visible) {
        chatButton.setImageTintList(ColorStateList.valueOf(visible
                ? Color.rgb(255, 54, 88)
                : Color.rgb(238, 211, 220)));
        chatButton.setContentDescription(visible ? "Ocultar conversación" : "Mostrar conversación");
    }

    private boolean isHomeUrl(String value) {
        if (value == null || !sameOrigin(value)) return false;
        try {
            String path = URI.create(value).getPath();
            return path == null || path.isEmpty() || "/".equals(path);
        } catch (RuntimeException error) {
            return false;
        }
    }

    private int effectivePort(URI value) {
        if (value.getPort() >= 0) return value.getPort();
        return "https".equalsIgnoreCase(value.getScheme()) ? 443 : 80;
    }

    private String configuredUrl() {
        String value = getSharedPreferences(PREFS, MODE_PRIVATE)
                .getString(URL_KEY, BuildConfig.DEFAULT_JARVIS_URL);
        return value == null ? "" : value.replaceAll("/+$", "");
    }

    private void showServerDialog(boolean cancelable) {
        EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setText(configuredUrl());
        input.setHint("https://jarvis.tu-tailnet.ts.net");
        input.setTextColor(Color.WHITE);
        input.setHintTextColor(Color.GRAY);
        input.setPadding(dp(12), dp(8), dp(12), dp(8));
        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle("Enlace privado con Jarvis")
                .setMessage("Usa la dirección HTTPS de Tailscale Serve. Se guarda solo en este teléfono.")
                .setView(input)
                .setNegativeButton(cancelable ? "Cancelar" : "Salir", (value, which) -> {
                    if (!cancelable) finish();
                })
                .setPositiveButton("Conectar", null)
                .create();
        dialog.setOnShowListener(ignored -> dialog.getButton(AlertDialog.BUTTON_POSITIVE)
                .setOnClickListener(view -> {
                    String url = input.getText().toString().trim().replaceAll("/+$", "");
                    if (!validHttpsUrl(url)) {
                        input.setError("Usa una dirección HTTPS válida");
                        return;
                    }
                    getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(URL_KEY, url).apply();
                    AmbientVoiceService.stop(this);
                    webView.loadUrl(url);
                    updateAppBarState();
                    dialog.dismiss();
                }));
        dialog.setCancelable(cancelable);
        dialog.show();
    }

    private boolean validHttpsUrl(String value) {
        try {
            URI uri = URI.create(value);
            return "https".equalsIgnoreCase(uri.getScheme())
                    && uri.getHost() != null
                    && uri.getRawUserInfo() == null
                    && (uri.getPath().isEmpty() || "/".equals(uri.getPath()))
                    && uri.getRawQuery() == null
                    && uri.getRawFragment() == null;
        } catch (RuntimeException error) {
            return false;
        }
    }

    private boolean handlePushToTalkTouch(View view, MotionEvent event) {
        if (event.getActionMasked() == MotionEvent.ACTION_DOWN) {
            if (!hasAudioPermission()) {
                ambientPermissionPending = false;
                requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, AUDIO_PERMISSION);
                Toast.makeText(
                        this,
                        "Concede el micrófono y vuelve a mantener pulsado para hablar",
                        Toast.LENGTH_LONG).show();
                return true;
            }
            if (!webConnectionReady) {
                webView.evaluateJavascript("window.jarvisMobileVoice?.syncNativeState?.()", null);
                Toast.makeText(
                        this,
                        "Desbloquea Jarvis con tu biometría antes de usar la voz",
                        Toast.LENGTH_LONG).show();
                return true;
            }
            if ("processing".equals(voiceState)) {
                Toast.makeText(this, "Jarvis todavía está procesando", Toast.LENGTH_SHORT).show();
                return true;
            }
            pushToTalkPressed = true;
            pendingVoiceSubmit = false;
            voiceState = "starting";
            updateVoiceButtons();
            connectionStatus.setText("PREPARANDO MICRÓFONO…");
            connectionStatus.setTextColor(Color.rgb(255, 54, 88));
            if (AmbientVoiceService.isRunning()) {
                AmbientVoiceService.stop(this);
                Toast.makeText(
                        this,
                        "Voz ambiental desactivada para usar pulsar y hablar",
                        Toast.LENGTH_SHORT).show();
                waitForAmbientStop(0);
            } else {
                startPushToTalk();
            }
            return true;
        }
        if (event.getActionMasked() == MotionEvent.ACTION_UP) {
            view.performClick();
            stopPushToTalk(true);
            return true;
        }
        if (event.getActionMasked() == MotionEvent.ACTION_CANCEL) {
            stopPushToTalk(false);
            return true;
        }
        return true;
    }

    private void waitForAmbientStop(int attempt) {
        if (!pushToTalkPressed) return;
        if (!AmbientVoiceService.isRunning()) {
            startPushToTalk();
            return;
        }
        if (attempt >= 20) {
            pushToTalkPressed = false;
            voiceState = "idle";
            updateVoiceButtons();
            Toast.makeText(this, "El micrófono ambiental tardó en cerrarse", Toast.LENGTH_LONG).show();
            updateAppBarState();
            return;
        }
        pushToTalkButton.postDelayed(() -> waitForAmbientStop(attempt + 1), 100);
    }

    private void startPushToTalk() {
        if (!pushToTalkPressed) return;
        if (!isHomeUrl(webView.getUrl())) {
            startPushToTalkAfterLoad = true;
            loadAppPath("");
            return;
        }
        voiceState = "starting";
        int generation = ++voiceStartGeneration;
        webView.evaluateJavascript(
                "(() => {"
                        + "if (window.jarvisMobileVoice?.start) window.jarvisMobileVoice.start();"
                        + "else window.JarvisNative?.onVoiceState('error', 'La interfaz de voz no está lista');"
                        + "})()",
                null);
        pushToTalkButton.postDelayed(() -> {
            if (generation != voiceStartGeneration || !"starting".equals(voiceState)) return;
            requestVoiceStop(false);
            pushToTalkPressed = false;
            Toast.makeText(
                    this,
                    "El micrófono no respondió. Recarga Jarvis e inténtalo otra vez.",
                    Toast.LENGTH_LONG).show();
        }, 12_000);
    }

    private void stopPushToTalk(boolean submit) {
        if (!pushToTalkPressed
                && !startPushToTalkAfterLoad
                && !"starting".equals(voiceState)
                && !"recording".equals(voiceState)) return;
        pushToTalkPressed = false;
        if (startPushToTalkAfterLoad) {
            startPushToTalkAfterLoad = false;
            pendingVoiceSubmit = false;
            voiceState = "idle";
            updateVoiceButtons();
            connectionStatus.setText("MANTÉN PULSADO CUANDO CARGUE INICIO");
            connectionStatus.postDelayed(this::updateAppBarState, 1200);
            return;
        }
        if ("starting".equals(voiceState) && submit) {
            pendingVoiceSubmit = true;
            connectionStatus.setText("FINALIZANDO CAPTURA…");
            updateVoiceButtons();
            return;
        }
        requestVoiceStop(submit);
    }

    private void requestVoiceStop(boolean submit) {
        pendingVoiceSubmit = false;
        if (isHomeUrl(webView.getUrl())) {
            webView.evaluateJavascript(
                    submit
                            ? "window.jarvisMobileVoice?.stop?.()"
                            : "window.jarvisMobileVoice?.cancel?.()",
                    null);
        }
        voiceState = submit ? "processing" : "idle";
        updateVoiceButtons();
        connectionStatus.setText(submit ? "PROCESANDO VOZ…" : "MICRÓFONO CERRADO");
        connectionStatus.setTextColor(submit
                ? Color.rgb(190, 138, 156)
                : Color.rgb(93, 243, 189));
        if (!submit) connectionStatus.postDelayed(this::updateAppBarState, 900);
    }

    private void toggleAmbient() {
        if (AmbientVoiceService.isRunning()) {
            AmbientVoiceService.stop(this);
            connectionStatus.setText("DETENIENDO VOZ…");
            connectionStatus.postDelayed(this::updateAppBarState, 600);
            return;
        }
        if (!webConnectionReady) {
            webView.evaluateJavascript("window.jarvisMobileVoice?.syncNativeState?.()", null);
            Toast.makeText(
                    this,
                    "Desbloquea Jarvis con tu biometría antes de activar el micrófono",
                    Toast.LENGTH_LONG).show();
            return;
        }
        if (configuredUrl().isEmpty()) {
            showServerDialog(false);
            return;
        }
        if (!hasAudioPermission()) {
            ambientPermissionPending = true;
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, AUDIO_PERMISSION);
            return;
        }
        ambientPermissionPending = false;
        AmbientVoiceService.start(this, configuredUrl());
        connectionStatus.setText("INICIANDO VOZ…");
        connectionStatus.postDelayed(this::updateAppBarState, 600);
        Toast.makeText(this, "Voz ambiental activa; usa la notificación para detenerla", Toast.LENGTH_LONG).show();
    }

    private boolean hasAudioPermission() {
        return checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED;
    }

    private void requestNotificationPermission() {
        if (android.os.Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(
                    new String[]{Manifest.permission.POST_NOTIFICATIONS}, NOTIFICATION_PERMISSION);
        }
    }

    private void updateAppBarState() {
        updateVoiceButtons();
        if ("locked".equals(webConnectionState)) {
            connectionStatus.setText("BLOQUEADO · USA TU BIOMETRÍA");
            connectionStatus.setTextColor(Color.rgb(255, 92, 112));
        } else if ("offline".equals(webConnectionState)) {
            connectionStatus.setText("SIN ENLACE CON TU PC");
            connectionStatus.setTextColor(Color.rgb(255, 92, 112));
        } else if (!webConnectionReady) {
            connectionStatus.setText("CONECTANDO…");
            connectionStatus.setTextColor(Color.rgb(190, 138, 156));
        } else if (AmbientVoiceService.isRunning()) {
            connectionStatus.setText("VOZ AMBIENTAL · ACTIVA");
            connectionStatus.setTextColor(Color.rgb(76, 255, 164));
        } else {
            connectionStatus.setText("TAILSCALE · CONECTADO");
            connectionStatus.setTextColor(Color.rgb(93, 243, 189));
        }
    }

    private void updateVoiceButtons() {
        boolean ambientRunning = AmbientVoiceService.isRunning();
        boolean voiceEnabled = webConnectionReady;
        ambientButton.setEnabled(voiceEnabled || ambientRunning);
        pushToTalkButton.setEnabled(voiceEnabled);
        ambientButton.setAlpha(voiceEnabled || ambientRunning ? 1f : 0.48f);
        pushToTalkButton.setAlpha(voiceEnabled ? 1f : 0.48f);
        ambientButton.setImageTintList(ColorStateList.valueOf(ambientRunning
                ? Color.rgb(76, 255, 164)
                : Color.rgb(238, 211, 220)));
        ambientButton.setContentDescription(
                ambientRunning ? "Desactivar voz ambiental" : "Activar voz ambiental");
        pushToTalkButton.setImageTintList(ColorStateList.valueOf(pushToTalkPressed
                ? Color.rgb(255, 54, 88)
                : Color.rgb(238, 211, 220)));
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(code, permissions, results);
        if (code == AUDIO_PERMISSION && results.length > 0
                && results[0] == PackageManager.PERMISSION_GRANTED) {
            if (ambientPermissionPending) {
                ambientPermissionPending = false;
                AmbientVoiceService.start(this, configuredUrl());
                connectionStatus.postDelayed(this::updateAppBarState, 600);
            }
        } else if (code == AUDIO_PERMISSION) {
            new AlertDialog.Builder(this)
                    .setTitle("Micrófono desactivado")
                    .setMessage("Puedes seguir escribiendo. Para usar voz ambiental, habilita el micrófono en Ajustes.")
                    .setPositiveButton("Abrir ajustes", (dialog, which) -> startActivity(new Intent(
                            Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                            Uri.parse("package:" + getPackageName()))))
                    .setNegativeButton("Ahora no", null)
                    .show();
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != FILE_CHOOSER || fileCallback == null) return;
        Uri[] value = resultCode == RESULT_OK ? WebChromeClient.FileChooserParams.parseResult(
                resultCode, data) : null;
        fileCallback.onReceiveValue(value);
        fileCallback = null;
    }

    @Override
    protected void onResume() {
        super.onResume();
        updateAppBarState();
    }

    @Override
    protected void onPause() {
        stopPushToTalk(false);
        super.onPause();
    }

    @Override
    @SuppressWarnings("deprecation")
    @SuppressLint("GestureBackNavigation")
    public void onBackPressed() {
        handleBack();
    }

    private void handleBack() {
        boolean chatVisible = getSharedPreferences(PREFS, MODE_PRIVATE)
                .getBoolean(CHAT_VISIBLE_KEY, false);
        if (chatVisible && isHomeUrl(webView.getUrl())) {
            getSharedPreferences(PREFS, MODE_PRIVATE)
                    .edit()
                    .putBoolean(CHAT_VISIBLE_KEY, false)
                    .apply();
            applyMobileShell();
            return;
        }
        if (webView.canGoBack()) {
            webView.goBack();
        } else {
            finishAfterTransition();
        }
    }

    @Override
    protected void onDestroy() {
        if (android.os.Build.VERSION.SDK_INT >= 33 && backCallback != null) {
            getOnBackInvokedDispatcher().unregisterOnBackInvokedCallback(backCallback);
        }
        webView.destroy();
        super.onDestroy();
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
