import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'providers/theme_provider.dart';
import 'providers/etf_provider.dart';
import 'providers/watchlist_provider.dart';
import 'providers/sync_provider.dart';
import 'app.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final themeProvider = ThemeProvider();
  await themeProvider.init();

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: themeProvider),
        ChangeNotifierProvider(create: (_) => EtfProvider()),
        ChangeNotifierProvider(create: (_) => WatchlistProvider()..loadData()),
        ChangeNotifierProvider(create: (_) => SyncProvider()),
      ],
      child: const YuQuantApp(),
    ),
  );
}
