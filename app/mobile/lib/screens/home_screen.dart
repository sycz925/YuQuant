import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../config/theme.dart';
import '../providers/theme_provider.dart';
import '../providers/etf_provider.dart';
import 'etf_list_screen.dart';
import 'watchlist_screen.dart';
import 'index_list_screen.dart';
import 'sync_dialog.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _currentIndex = 0;

  final _screens = [
    const EtfListScreen(),
    const WatchlistScreen(),
    const IndexListScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Scaffold(
      appBar: AppBar(
        title: const Text('A股ETF量化'),
        actions: [
          IconButton(
            icon: const Icon(Icons.sync),
            onPressed: () async {
              await SyncDialog.show(context);
              if (mounted) {
                context.read<EtfProvider>().loadData();
              }
            },
          ),
          IconButton(
            icon: Icon(
              context.watch<ThemeProvider>().isDark ? Icons.light_mode : Icons.dark_mode,
            ),
            onPressed: () => context.read<ThemeProvider>().toggleTheme(),
          ),
        ],
      ),
      body: _screens[_currentIndex],
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentIndex,
        onTap: (index) => setState(() => _currentIndex = index),
        type: BottomNavigationBarType.fixed,
        selectedItemColor: AppColors.darkAccent,
        unselectedItemColor: isDark ? AppColors.darkTextSecondary : AppColors.lightTextSecondary,
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.list), label: 'ETF列表'),
          BottomNavigationBarItem(icon: Icon(Icons.star), label: '自选股'),
          BottomNavigationBarItem(icon: Icon(Icons.show_chart), label: '指数'),
        ],
      ),
    );
  }
}
