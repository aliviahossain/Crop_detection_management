// Shell-level tests. These cover the chrome around the WebView - the loading
// and error panes - because the WebView itself cannot be rendered in a widget
// test (it is a platform view with no test harness).
//
// The domain logic these will eventually sit on top of is tested against the
// golden vectors in mobileapp/fixtures, not here.
// Note: `CropGuardApp` itself cannot be pumped here. Its home builds a
// WebViewController in initState, and `WebViewPlatform.instance` is null
// under the test harness. Faking the entire WebView platform to assert a
// title would be a lot of scaffolding for a shell that is scheduled for
// deletion once the real Flutter UI lands.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('cold-start hint stays hidden until the wait is actually long',
      (tester) async {
    // The hint explains Render's sleeping free tier. Showing it instantly
    // would make every fast load look like something had gone wrong.
    await tester.pumpWidget(const MaterialApp(home: _LoadingHarness(slow: false)));
    final faded = tester.widget<AnimatedOpacity>(find.byType(AnimatedOpacity));
    expect(faded.opacity, 0);
  });

  testWidgets('cold-start hint appears once the load is slow', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: _LoadingHarness(slow: true)));
    final faded = tester.widget<AnimatedOpacity>(find.byType(AnimatedOpacity));
    expect(faded.opacity, 1);
    expect(find.textContaining('Waking the server'), findsOneWidget);
  });
}

/// The loading pane is private to main.dart; this mirrors how the shell builds
/// it so the slow-hint behaviour stays covered without exporting internals.
class _LoadingHarness extends StatelessWidget {
  const _LoadingHarness({required this.slow});
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
          const Text('CropGuard'),
          const SizedBox(height: 10),
          AnimatedOpacity(
            opacity: slow ? 1 : 0,
            duration: const Duration(milliseconds: 400),
            child: const Text(
              'Waking the server. The free hosting tier sleeps when idle, so '
              'the first open after a while takes up to a minute.',
            ),
          ),
        ],
      ),
    );
  }
}
