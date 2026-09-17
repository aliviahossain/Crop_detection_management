/// First-launch crop selection, and the one screen that needs a connection.
///
/// A crop is a downloadable pack, not an app release, so the app ships without
/// weights and asks once which crop this farmer grows. Everything after that
/// runs with the radio off.
///
/// The screen is deliberately skippable. Weather-driven risk forecasting, the
/// scouting alert and the triage gate all work with no pack at all, and a
/// farmer standing in a field with one bar should not be blocked from those by
/// a 45 MB download they can do tonight at home.
library;

import 'package:flutter/material.dart';

import 'pack.dart';
import 'pack_store.dart';

class CropPickerPage extends StatefulWidget {
  const CropPickerPage({
    super.key,
    required this.onDone,
    required this.onSkip,
    this.store,
  });

  final VoidCallback onDone;
  final VoidCallback onSkip;
  final PackStore? store;

  @override
  State<CropPickerPage> createState() => _CropPickerPageState();
}

class _CropPickerPageState extends State<CropPickerPage> {
  PackStore get _store => widget.store ?? PackStore.instance;

  List<CatalogCrop>? _crops;
  String? _error;
  bool _loading = true;
  PackProgress? _progress;
  String? _installing;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final crops = await _store.catalog();
      if (!mounted) return;
      setState(() {
        _crops = crops;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = '$e';
        _loading = false;
      });
    }
  }

  Future<void> _install(CatalogCrop crop) async {
    final version = crop.latestVersion;
    if (version == null) return;
    setState(() {
      _installing = crop.crop;
      _error = null;
      _progress = null;
    });
    try {
      await _store.install(
        crop,
        version,
        onProgress: (p) {
          if (mounted) setState(() => _progress = p);
        },
      );
      if (!mounted) return;
      widget.onDone();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _installing = null;
        _progress = null;
        _error = '$e';
      });
    }
  }

  String _size(int bytes) => bytes < 1024 * 1024
      ? '${(bytes / 1024).round()} KB'
      : '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Choose your crop',
                  style: theme.textTheme.headlineSmall
                      ?.copyWith(fontWeight: FontWeight.w600)),
              const SizedBox(height: 8),
              Text(
                'CropGuard downloads one crop pack, once. After that, diagnosis '
                'and treatment advice work with no network at all.',
                style: theme.textTheme.bodyMedium
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
              const SizedBox(height: 20),
              Expanded(child: _body(theme)),
              if (_installing == null) ...[
                const SizedBox(height: 8),
                Center(
                  child: TextButton(
                    onPressed: widget.onSkip,
                    child: const Text('Skip for now'),
                  ),
                ),
                Text(
                  'Weather risk forecasting and scouting alerts work without a '
                  'crop pack. Photo diagnosis and treatment advice need one.',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.outline),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _body(ThemeData theme) {
    if (_installing != null) return _installingView(theme);
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return _errorView(theme);
    }
    final crops = _crops ?? const [];
    if (crops.isEmpty) {
      return Center(
        child: Text(
          'The catalogue has no crops in it yet.',
          style: theme.textTheme.bodyMedium,
        ),
      );
    }
    return ListView.separated(
      itemCount: crops.length,
      separatorBuilder: (_, _) => const SizedBox(height: 12),
      itemBuilder: (context, i) {
        final crop = crops[i];
        final v = crop.latestVersion;
        return Card(
          margin: EdgeInsets.zero,
          child: ListTile(
            contentPadding:
                const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            title: Text(
              crop.crop[0].toUpperCase() + crop.crop.substring(1),
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            subtitle: Text(
              v == null
                  ? 'No version available'
                  : '${v.classes.length} conditions detected  -  '
                      '${_size(v.totalBytes)} download  -  v${v.version}',
            ),
            trailing: FilledButton(
              onPressed: v == null ? null : () => _install(crop),
              child: const Text('Install'),
            ),
          ),
        );
      },
    );
  }

  Widget _installingView(ThemeData theme) {
    final p = _progress;
    // An indeterminate bar for the manifest fetch, a real one once the payload
    // size is known. A bar that sits at 0% for ten seconds reads as a hang.
    final fraction = p == null || p.totalBytes <= 0 ? null : p.fraction;
    final label = switch (p?.phase) {
      'manifest' => 'Checking the pack...',
      'verify' => 'Verifying ${p?.file ?? ''}',
      'install' => 'Installing...',
      'done' => 'Done',
      _ => 'Downloading ${p?.file ?? ''}',
    };
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          LinearProgressIndicator(value: fraction),
          const SizedBox(height: 20),
          Text(label, style: theme.textTheme.bodyMedium),
          const SizedBox(height: 6),
          if (p != null && p.totalBytes > 0)
            Text(
              '${_size(p.receivedBytes)} of ${_size(p.totalBytes)}',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.outline),
            ),
          const SizedBox(height: 16),
          Text(
            'This happens once. Keep the app open until it finishes.',
            textAlign: TextAlign.center,
            style: theme.textTheme.bodySmall
                ?.copyWith(color: theme.colorScheme.outline),
          ),
        ],
      ),
    );
  }

  Widget _errorView(ThemeData theme) => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.cloud_off_rounded,
                size: 44, color: theme.colorScheme.outline),
            const SizedBox(height: 16),
            Text('Could not get the crop list',
                style: theme.textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(
              _error ?? '',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.outline),
            ),
            const SizedBox(height: 20),
            FilledButton.icon(
              onPressed: _load,
              icon: const Icon(Icons.refresh),
              label: const Text('Try again'),
            ),
          ],
        ),
      );
}
