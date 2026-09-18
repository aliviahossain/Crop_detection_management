// CropGuard Android app - fully offline.
//
// The UI is the CropGuard web app, bundled into the APK. The backend it talks
// to is `LocalServer`, running on 127.0.0.1 inside this process, implementing
// the agronomic models, the triage safety gate and the taxonomy in Dart. There
// is no network call anywhere in the farmer's path: install it, turn on
// airplane mode, and risk forecasting and advisories still work.
//
// What is still online-only - cross-farm outbreak pressure, the hotspot map,
// the officer dashboard and expert review - is listed at the top of
// local_server.dart and reported as such by /meta/health rather than faked.
import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:file_picker/file_picker.dart';

import 'local_server.dart';
import 'packs/crop_picker.dart';
import 'packs/pack_store.dart';

// The on-device server binds to an OS-assigned port, so the URL is not known
// until it starts.
const Duration kColdStartHint = Duration(seconds: 8);

void main() => runApp(const CropGuardApp());

class CropGuardApp extends StatelessWidget {
  const CropGuardApp({super.key});

  @override
  Widget build(BuildContext context) {
    const seed = Color(0xFF1F6B45); // CropGuard green, matches the web header
    return MaterialApp(
      title: 'CropGuard',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: seed),
        useMaterial3: true,
      ),
      home: const WebShell(),
    );
  }
}

class WebShell extends StatefulWidget {
  const WebShell({super.key});

  @override
  State<WebShell> createState() => _WebShellState();
}

class _WebShellState extends State<WebShell> {
  WebViewController? _controller;
  String? _origin;
  bool _loading = true;
  bool _slow = false;
  String? _error;

  /// True once we know whether a crop pack is installed. Until then neither
  /// the picker nor the WebView should be shown, or a farmer who already chose
  /// a crop would see the picker flash on every cold start.
  bool _packChecked = false;
  bool _needsCrop = false;

  @override
  void initState() {
    super.initState();
    _requestCamera();
    _boot();
  }

  /// Start the on-device server, then point the WebView at it. The port is
  /// assigned by the OS, so the controller cannot be built until this resolves.
  Future<void> _boot() async {
    try {
      final origin = await LocalServer.instance.start();
      debugPrint('[cropguard] on-device server listening at $origin');

      // Ask which crop before loading the UI, not after: the scanner reads
      // /detect/status once at startup, so a pack installed later would leave
      // the page convinced there is no detector until a manual reload.
      final pack = await PackStore.instance.activePack();
      debugPrint('[cropguard] active pack: '
          '${pack == null ? 'none' : '${pack.crop}@${pack.version}'}');
      if (!mounted) return;
      if (pack == null) {
        setState(() {
          _origin = origin;
          _packChecked = true;
          _needsCrop = true;
          _loading = false;
        });
        return;
      }

      setState(() {
        _origin = origin;
        _packChecked = true;
        _controller = _buildController(origin);
      });
    } catch (e, st) {
      // Without this the only symptom is a generic error pane, which tells
      // nobody anything. adb logcat is the one place this can surface.
      debugPrint('[cropguard] server failed to start: $e\n$st');
      if (mounted) {
        setState(() {
          _loading = false;
          _error = 'Could not start the on-device server: $e';
        });
      }
    }
  }

  @override
  void dispose() {
    LocalServer.instance.stop();
    super.dispose();
  }

  // The live scanner needs the camera. Ask up front rather than letting the
  // WebView's own prompt appear with no context mid-scan.
  Future<void> _requestCamera() async {
    await Permission.camera.request();
  }

  WebViewController _buildController(String origin) {
    final c = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(Colors.white)
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageStarted: (_) {
            if (!mounted) return;
            setState(() {
              _loading = true;
              _slow = false;
              _error = null;
            });
            Future.delayed(kColdStartHint, () {
              if (mounted && _loading) setState(() => _slow = true);
            });
          },
          onPageFinished: (_) {
            if (mounted) setState(() => _loading = false);
          },
          onWebResourceError: (err) {
            debugPrint('[cropguard] webview error: ${err.errorCode} '
                '${err.errorType} mainFrame=${err.isForMainFrame} '
                'url=${err.url} :: ${err.description}');
            // Subframe and asset errors are noisy and mostly harmless; only a
            // failure of the main document is worth showing the user.
            if (err.isForMainFrame != true) return;
            if (mounted) {
              setState(() {
                _loading = false;
                _error = err.description;
              });
            }
          },
        ),
      );

    // Forward the page's console to logcat. Without this a JavaScript error
    // inside the bundled UI is completely invisible from the host: the WebView
    // just goes white, `onWebResourceError` says nothing because the document
    // loaded fine, and the only way to tell a blank page from a crashed one is
    // to guess. `adb logcat -s flutter` now shows the actual stack.
    c.setOnConsoleMessage((msg) {
      debugPrint('[cropguard][web] ${msg.level.name}: ${msg.message}');
    });

    // Android specifics: grant the WebView's camera request (the scanner), and
    // allow getUserMedia without a synthetic user gesture.
    final platform = c.platform;
    if (platform is AndroidWebViewController) {
      platform.setMediaPlaybackRequiresUserGesture(false);
      platform.setOnPlatformPermissionRequest((request) => request.grant());

      // Without this, every <input type="file"> in the page does NOTHING.
      //
      // Android's WebView does not open a file chooser on its own: it asks the
      // host app via onShowFileChooser, and a host that does not answer leaves
      // the tap silently dead - no picker, no error, no console message. That
      // is the worst kind of bug to report, because there is nothing to report.
      // It took out video upload on both lab scanners and the photo picker on
      // Check crop.
      platform.setOnShowFileSelector(_pickFiles);
    }

    c.loadRequest(Uri.parse(origin));
    return c;
  }

  /// Answers the page's `<input type="file">`.
  ///
  /// Returns file:// URIs, or an empty list when the user backs out - which the
  /// WebView reads as "cancelled" and leaves the input untouched, so the same
  /// clip can be picked again afterwards.
  Future<List<String>> _pickFiles(FileSelectorParams params) async {
    final accepts = params.acceptTypes.join(',');
    final wantsVideo = accepts.contains('video');
    final wantsImage = accepts.contains('image');

    // Narrow the picker to what the input actually asked for. `accept="video/*"`
    // showing a photo grid is how you get a farmer picking a still that the
    // clip scanner then refuses.
    final FileType type;
    if (wantsVideo && !wantsImage) {
      type = FileType.video;
    } else if (wantsImage && !wantsVideo) {
      type = FileType.image;
    } else if (wantsImage || wantsVideo) {
      type = FileType.media;
    } else {
      type = FileType.any;
    }

    try {
      final result = await FilePicker.platform.pickFiles(
        type: type,
        allowMultiple: params.mode == FileSelectorMode.openMultiple,
      );
      if (result == null) return const [];
      return [
        for (final f in result.files)
          if (f.path != null) Uri.file(f.path!).toString(),
      ];
    } catch (e) {
      // A picker that throws must still return, or the WebView leaves the
      // input in a pending state and the next tap does nothing either.
      debugPrint('[cropguard] file selector failed: $e');
      return const [];
    }
  }

  /// Leaves the picker, either with a pack installed or explicitly skipped.
  void _leavePicker() {
    final origin = _origin;
    if (origin == null) return;
    setState(() {
      _needsCrop = false;
      _loading = true;
      _controller = _buildController(origin);
    });
  }

  Future<void> _reload() async {
    final origin = _origin;
    final controller = _controller;
    if (origin == null || controller == null) {
      // The server never came up - retry the whole boot rather than reloading
      // a URL that does not exist yet.
      setState(() {
        _error = null;
        _loading = true;
        _slow = false;
      });
      return _boot();
    }
    setState(() {
      _error = null;
      _loading = true;
      _slow = false;
    });
    await controller.loadRequest(Uri.parse(origin));
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      // Back should walk the app's own history, not drop the user out of the
      // app from three screens deep.
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        // Resolve the navigator before the await so no BuildContext is held
        // across the async gap.
        final navigator = Navigator.of(context);
        final controller = _controller;
        if (controller != null && await controller.canGoBack()) {
          await controller.goBack();
          return;
        }
        navigator.maybePop();
      },
      child: _needsCrop
          ? CropPickerPage(onDone: _leavePicker, onSkip: _leavePicker)
          : Scaffold(
              body: SafeArea(
                child: Stack(
                  children: [
                    if (_controller != null)
                      WebViewWidget(controller: _controller!),
                    if (_error != null)
                      _ErrorPane(message: _error!, onRetry: _reload),
                    if ((_loading || !_packChecked) && _error == null)
                      _LoadingPane(slow: _slow),
                  ],
                ),
              ),
            ),
    );
  }
}

class _LoadingPane extends StatelessWidget {
  const _LoadingPane({required this.slow});
  final bool slow;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.white,
      alignment: Alignment.center,
      padding: const EdgeInsets.symmetric(horizontal: 32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const CircularProgressIndicator(),
          const SizedBox(height: 28),
          Text(
            'CropGuard',
            style: Theme.of(context)
                .textTheme
                .headlineSmall
                ?.copyWith(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 10),
          AnimatedOpacity(
            opacity: slow ? 1 : 0,
            duration: const Duration(milliseconds: 400),
            child: Text(
              'Starting the on-device engine. Everything runs locally, so this '
              'works with no network at all.',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ErrorPane extends StatelessWidget {
  const _ErrorPane({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.white,
      alignment: Alignment.center,
      padding: const EdgeInsets.symmetric(horizontal: 32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.cloud_off_rounded,
              size: 48, color: Theme.of(context).colorScheme.outline),
          const SizedBox(height: 20),
          Text(
            'CropGuard could not start',
            style: Theme.of(context)
                .textTheme
                .titleLarge
                ?.copyWith(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 10),
          Text(
            'This is not a network problem - the app runs entirely on your '
            'phone. The on-device engine failed to start.',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
          ),
          const SizedBox(height: 8),
          Text(
            message,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.outline,
                ),
          ),
          const SizedBox(height: 24),
          FilledButton.icon(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh),
            label: const Text('Try again'),
          ),
        ],
      ),
    );
  }
}
