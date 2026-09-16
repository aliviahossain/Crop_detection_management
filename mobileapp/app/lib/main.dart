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

import 'local_server.dart';

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
      if (!mounted) return;
      setState(() {
        _origin = origin;
        _controller = _buildController(origin);
      });
    } catch (e) {
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
            // Subframe and asset errors are noisy and mostly harmless; only a
            // failure of the main document is worth showing the user.
            if (!err.isForMainFrame!) return;
            if (mounted) {
              setState(() {
                _loading = false;
                _error = err.description;
              });
            }
          },
        ),
      );

    // Android specifics: grant the WebView's camera request (the scanner), and
    // allow getUserMedia without a synthetic user gesture.
    final platform = c.platform;
    if (platform is AndroidWebViewController) {
      platform.setMediaPlaybackRequiresUserGesture(false);
      platform.setOnPlatformPermissionRequest((request) => request.grant());
    }

    c.loadRequest(Uri.parse(origin));
    return c;
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
      child: Scaffold(
        body: SafeArea(
          child: Stack(
            children: [
              if (_controller != null)
                WebViewWidget(controller: _controller!),
              if (_error != null) _ErrorPane(message: _error!, onRetry: _reload),
              if (_loading && _error == null) _LoadingPane(slow: _slow),
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
