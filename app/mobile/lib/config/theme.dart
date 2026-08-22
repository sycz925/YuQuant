import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppColors {
  static const rise = Color(0xFFEF4444);
  static const fall = Color(0xFF22C55E);
  static const flat = Color(0xFF9CA3AF);

  static const darkPrimary = Color(0xFF0F0F1A);
  static const darkSurface = Color(0xFF1A1A2E);
  static const darkAccent = Color(0xFF7C3AED);
  static const darkTextPrimary = Color(0xFFF1F5F9);
  static const darkTextSecondary = Color(0xFF94A3B8);

  static const lightPrimary = Color(0xFFF8FAFC);
  static const lightSurface = Color(0xFFFFFFFF);
  static const lightAccent = Color(0xFF7C3AED);
  static const lightTextPrimary = Color(0xFF1E293B);
  static const lightTextSecondary = Color(0xFF64748B);
}

class AppTheme {
  static ThemeData get darkTheme {
    final baseDark = ThemeData.dark(useMaterial3: true);
    return baseDark.copyWith(
      primaryColor: AppColors.darkPrimary,
      scaffoldBackgroundColor: AppColors.darkPrimary,
      cardColor: AppColors.darkSurface,
      colorScheme: const ColorScheme.dark(
        primary: AppColors.darkAccent,
        surface: AppColors.darkSurface,
        error: AppColors.rise,
      ),
      textTheme: GoogleFonts.notoSansScTextTheme(baseDark.textTheme).apply(
        bodyColor: AppColors.darkTextPrimary,
        displayColor: AppColors.darkTextPrimary,
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: AppColors.darkPrimary,
        elevation: 0,
        centerTitle: true,
        titleTextStyle: GoogleFonts.notoSansSc(
          fontSize: 18,
          fontWeight: FontWeight.w600,
          color: AppColors.darkTextPrimary,
        ),
        iconTheme: const IconThemeData(color: AppColors.darkTextPrimary),
      ),
      cardTheme: CardTheme(
        color: AppColors.darkSurface,
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
      dividerColor: Colors.white10,
      snackBarTheme: SnackBarThemeData(
        backgroundColor: AppColors.darkSurface,
        contentTextStyle: GoogleFonts.notoSansSc(color: AppColors.darkTextPrimary),
      ),
    );
  }

  static ThemeData get lightTheme {
    final baseLight = ThemeData.light(useMaterial3: true);
    return baseLight.copyWith(
      primaryColor: AppColors.lightPrimary,
      scaffoldBackgroundColor: AppColors.lightPrimary,
      cardColor: AppColors.lightSurface,
      colorScheme: const ColorScheme.light(
        primary: AppColors.lightAccent,
        surface: AppColors.lightSurface,
        error: AppColors.rise,
      ),
      textTheme: GoogleFonts.notoSansScTextTheme(baseLight.textTheme),
      appBarTheme: AppBarTheme(
        backgroundColor: AppColors.lightPrimary,
        elevation: 0,
        centerTitle: true,
        titleTextStyle: GoogleFonts.notoSansSc(
          fontSize: 18,
          fontWeight: FontWeight.w600,
          color: AppColors.lightTextPrimary,
        ),
        iconTheme: const IconThemeData(color: AppColors.lightTextPrimary),
      ),
      cardTheme: CardTheme(
        color: AppColors.lightSurface,
        elevation: 0,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
      dividerColor: Colors.grey.shade200,
      snackBarTheme: SnackBarThemeData(
        backgroundColor: AppColors.lightSurface,
        contentTextStyle: GoogleFonts.notoSansSc(color: AppColors.lightTextPrimary),
      ),
    );
  }
}
