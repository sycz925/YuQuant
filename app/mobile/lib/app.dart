import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'config/theme.dart';
import 'providers/theme_provider.dart';
import 'screens/home_screen.dart';

class YuQuantApp extends StatelessWidget {
  const YuQuantApp({super.key});

  @override
  Widget build(BuildContext context) {
    return Consumer<ThemeProvider>(
      builder: (context, themeProvider, _) {
        return MaterialApp(
          title: 'YuQuant',
          theme: AppTheme.darkTheme,
          darkTheme: AppTheme.lightTheme,
          themeMode: themeProvider.themeMode,
          home: const HomeScreen(),
        );
      },
    );
  }
}
