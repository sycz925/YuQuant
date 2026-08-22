import 'package:flutter/material.dart';
import '../config/theme.dart';
import '../services/database.dart';
import '../models/index_basic.dart';
import '../models/daily_bar.dart';

class IndexListScreen extends StatefulWidget {
  const IndexListScreen({super.key});

  @override
  State<IndexListScreen> createState() => _IndexListScreenState();
}

class _IndexListScreenState extends State<IndexListScreen> {
  List<IndexBasic> _indices = [];
  Map<String, DailyBar> _latestBars = {};
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    final indices = await DatabaseHelper.instance.getIndexBasics(enabledOnly: true);
    final bars = await DatabaseHelper.instance.getAllLatestDailyBars('index');
    final latestMap = {for (final b in bars) b.stockCode: b};
    setState(() {
      _indices = indices;
      _latestBars = latestMap;
      _loading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    if (_loading) return const Center(child: CircularProgressIndicator());

    return ListView.builder(
      itemCount: _indices.length,
      itemBuilder: (context, index) {
        final idx = _indices[index];
        final bar = _latestBars[idx.code];
        final chgColor = (bar?.chgPct ?? 0) > 0
            ? AppColors.rise
            : (bar?.chgPct ?? 0) < 0
                ? AppColors.fall
                : AppColors.flat;

        return Card(
          margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
          color: isDark ? AppColors.darkSurface : AppColors.lightSurface,
          child: ListTile(
            title: Text('${idx.code} ${idx.name}', style: const TextStyle(fontSize: 14)),
            subtitle: bar != null
                ? Row(
                    children: [
                      Text('${bar.close?.toStringAsFixed(2) ?? '-'}', style: TextStyle(color: chgColor, fontSize: 12)),
                      const SizedBox(width: 8),
                      Text('${bar.chgPct?.toStringAsFixed(2) ?? '-'}%', style: TextStyle(color: chgColor, fontSize: 12)),
                    ],
                  )
                : const Text('暂无数据', style: TextStyle(fontSize: 12)),
          ),
        );
      },
    );
  }
}
