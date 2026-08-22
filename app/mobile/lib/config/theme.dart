import 'package:flutter/material.dart';

class AppColors {
  static const rise = Color(0xFFEF4444);
  static const fall = Color(0xFF22C55E);
  static const flat = Color(0xFF9CA3AF);

  static const darkPrimary = Color(0xFF1E1E2E);
  static const darkSurface = Color(0xFF2A2A3E);
  static const darkAccent = Color(0xFF7C3AED);
  static const darkTextPrimary = Color(0xFFE5E7EB);
  static const darkTextSecondary = Color(0xFF9CA3AF);

  static const lightPrimary = Color(0xFFF8FAFC);
  static const lightSurface = Color(0xFFFFFFFF);
  static const lightAccent = Color(0xFF7C3AED);
  static const lightTextPrimary = Color(0xFF1E293B);
  static const lightTextSecondary = Color(0xFF64748B);
}

class AppTheme {
  static ThemeData get darkTheme => ThemeData(
    brightness: Brightness.dark,
    primaryColor: AppColors.darkPrimary,
    scaffoldBackgroundColor: AppColors.darkPrimary,
    cardColor: AppColors.darkSurface,
    colorScheme: const ColorScheme.dark(
      primary: AppColors.darkAccent,
      surface: AppColors.darkSurface,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.darkPrimary,
      elevation: 0,
    ),
    dividerColor: AppColors.darkSurface,
  );

  static ThemeData get lightTheme => ThemeData(
    brightness: Brightness.light,
    primaryColor: AppColors.lightPrimary,
    scaffoldBackgroundColor: AppColors.lightPrimary,
    cardColor: AppColors.lightSurface,
    colorScheme: const ColorScheme.light(
      primary: AppColors.lightAccent,
      surface: AppColors.lightSurface,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.lightPrimary,
      elevation: 0,
    ),
    dividerColor: Colors.grey.shade200,
  );
}
