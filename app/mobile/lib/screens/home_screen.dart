import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:google_fonts/google_fonts.dart';
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
        title: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              padding: const EdgeInsets.all(6),
              decoration: BoxDecoration(
                color: AppColors.darkAccent.withOpacity(0.2),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Icon(Icons.show_chart, color: AppColors.darkAccent, size: 20),
            ),
            const SizedBox(width: 10),
            Text(
              'YuQuant',
              style: GoogleFonts.notoSansSc(
                fontWeight: FontWeight.w700,
                fontSize: 20,
                letterSpacing: 0.5,
              ),
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.sync, size: 22),
            onPressed: () async {
              await SyncDialog.show(context);
              if (mounted) {
                context.read<EtfProvider>().loadData();
              }
            },
          ),
          IconButton(
            icon: AnimatedSwitcher(
              duration: const Duration(milliseconds: 300),
              child: Icon(
                context.watch<ThemeProvider>().isDark ? Icons.light_mode : Icons.dark_mode,
                key: ValueKey(context.watch<ThemeProvider>().isDark),
                size: 22,
              ),
            ),
            onPressed: () => context.read<ThemeProvider>().toggleTheme(),
          ),
        ],
      ),
      body: _screens[_currentIndex],
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
          border: Border(
            top: BorderSide(
              color: isDark ? Colors.white10 : Colors.grey.shade200,
              width: 0.5,
            ),
          ),
        ),
        child: BottomNavigationBar(
          currentIndex: _currentIndex,
          onTap: (index) => setState(() => _currentIndex = index),
          type: BottomNavigationBarType.fixed,
          selectedItemColor: AppColors.darkAccent,
          unselectedItemColor: isDark ? AppColors.darkTextSecondary : AppColors.lightTextSecondary,
          selectedLabelStyle: GoogleFonts.notoSansSc(fontSize: 11, fontWeight: FontWeight.w600),
          unselectedLabelStyle: GoogleFonts.notoSansSc(fontSize: 11),
          items: const [
            BottomNavigationBarItem(icon: Icon(Icons.leaderboard), label: 'ETF列表'),
            BottomNavigationBarItem(icon: Icon(Icons.star), label: '自选股'),
            BottomNavigationBarItem(icon: Icon(Icons.candlestick_chart), label: '指数'),
          ],
        ),
      ),
    );
  }
}
