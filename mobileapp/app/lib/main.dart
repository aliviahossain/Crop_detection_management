// CropGuard Android shell.
//
// STOPGAP, NOT THE ARCHITECTURE. This wraps the deployed React frontend in a
// WebView so there is an installable APK today. It is online-only: every
// screen needs the Render backend, so it does the opposite of what the
// offline-first plan in ../README.md calls for.
//
// The real app replaces this entirely - a Flutter UI over the pure-Dart
// domain package, with the detector and knowledge base on the handset. Until
// that lands, this is what you hand someone who says "let me see it".
import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';
import 'package:permission_handler/permission_handler.dart';

const String kAppUrl = 'https://cropguard-frontend-rhzv.onrender.com/';

// Render's free tier sleeps after inactivity and takes the better part of a
// minute to wake. That is long enough that a bare spinner reads as "broken",
// so the loading screen says what is happening instead.
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
  late final WebViewController _controller;
  bool _loading = true;
  bool _slow = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _requestCamera();
    _controller = _buildController();
  }

  // The live scanner needs the camera. Ask up front rather than letting the
  // WebView's own prompt appear with no context mid-scan.
  Future<void> _requestCamera() async {
    await Permission.camera.request();
  }

  WebViewController _buildController() {
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

    c.loadRequest(Uri.parse(kAppUrl));
    return c;
  }

  Future<void> _reload() async {
    setState(() {
      _error = null;
      _loading = true;
      _slow = false;
    });
    await _controller.loadRequest(Uri.parse(kAppUrl));
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
        if (await _controller.canGoBack()) {
          await _controller.goBack();
          return;
        }
        navigator.maybePop();
      },
      child: Scaffold(
        body: SafeArea(
          child: Stack(
            children: [
              WebViewWidget(controller: _controller),
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
              'Waking the server. The free hosting tier sleeps when idle, so '
              'the first open after a while takes up to a minute.',
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
            'Cannot reach CropGuard',
            style: Theme.of(context)
                .textTheme
                .titleLarge
                ?.copyWith(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 10),
          Text(
            'This build needs an internet connection - every screen is served '
            'from the backend. Check your connection and try again.',
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
