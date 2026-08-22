import 'package:flutter/material.dart';
import 'package:k_chart/flutter_k_chart.dart';
import '../config/theme.dart';
import '../services/database.dart';
import '../models/daily_bar.dart';

class EtfDetailScreen extends StatefulWidget {
  final String code;
  final String name;
  const EtfDetailScreen({super.key, required this.code, required this.name});

  @override
  State<EtfDetailScreen> createState() => _EtfDetailScreenState();
}

class _EtfDetailScreenState extends State<EtfDetailScreen> {
  List<DailyBar> _bars = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    final bars = await DatabaseHelper.instance.getDailyBars('etf', widget.code, limit: 120);
    setState(() {
      _bars = bars.reversed.toList();
      _loading = false;
    });
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final latest = _bars.isNotEmpty ? _bars.last : null;
    final chgColor = (latest?.chgPct ?? 0) > 0 ? AppColors.rise : (latest?.chgPct ?? 0) < 0 ? AppColors.fall : AppColors.flat;

    return Scaffold(
      appBar: AppBar(title: Text('${widget.code} ${widget.name}')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: [
                if (latest != null)
                  Container(
                    padding: const EdgeInsets.all(16),
                    color: isDark ? AppColors.darkSurface : AppColors.lightSurface,
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceAround,
                      children: [
                        _dataItem('现价', latest.close?.toStringAsFixed(3) ?? '-', chgColor),
                        _dataItem('涨跌%', '${latest.chgPct?.toStringAsFixed(2) ?? '-'}%', chgColor),
                        _dataItem('成交量', _formatVol(latest.vol), null),
                        _dataItem('成交额', _formatAmount(latest.amount), null),
                      ],
                    ),
                  ),
                Expanded(
                  child: _bars.isEmpty
                      ? const Center(child: Text('暂无K线数据'))
                      : _buildChart(isDark),
                ),
                if (latest != null)
                  Container(
                    padding: const EdgeInsets.all(8),
                    color: isDark ? AppColors.darkSurface : AppColors.lightSurface,
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceAround,
                      children: [
                        _dataItem('开', latest.open?.toStringAsFixed(3) ?? '-', null),
                        _dataItem('高', latest.high?.toStringAsFixed(3) ?? '-', null),
                        _dataItem('低', latest.low?.toStringAsFixed(3) ?? '-', null),
                        _dataItem('收', latest.close?.toStringAsFixed(3) ?? '-', null),
                      ],
                    ),
                  ),
              ],
            ),
    );
  }

  Widget _buildChart(bool isDark) {
    final data = _bars.map((bar) {
      return KLineEntity.fromCustom(
        open: bar.open ?? 0,
        close: bar.close ?? 0,
        high: bar.high ?? 0,
        low: bar.low ?? 0,
        vol: bar.vol?.toDouble() ?? 0,
        amount: bar.amount ?? 0,
        time: DateTime.parse(bar.tradeDate).millisecondsSinceEpoch,
      );
    }).toList();

    ChartColors colors = ChartColors();
    if (isDark) {
      colors.bgColor = [AppColors.darkPrimary, AppColors.darkPrimary];
      colors.gridColor = AppColors.darkSurface;
      colors.defaultTextColor = AppColors.darkTextSecondary;
    } else {
      colors.bgColor = [AppColors.lightPrimary, AppColors.lightPrimary];
      colors.gridColor = Colors.grey.shade200;
      colors.defaultTextColor = AppColors.lightTextSecondary;
    }
    colors.upColor = AppColors.rise;
    colors.dnColor = AppColors.fall;

    return Padding(
      padding: const EdgeInsets.all(8.0),
      child: KChartWidget(
        data,
        ChartStyle(),
        colors,
        isTrendLine: false,
      ),
    );
  }

  Widget _dataItem(String label, String value, Color? color) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(label, style: TextStyle(fontSize: 11, color: Colors.grey)),
        Text(value, style: TextStyle(fontSize: 13, color: color, fontWeight: FontWeight.bold)),
      ],
    );
  }

  String _formatVol(double? vol) {
    if (vol == null) return '-';
    if (vol >= 10000) return '${(vol / 10000).toStringAsFixed(1)}万';
    return vol.toStringAsFixed(0);
  }

  String _formatAmount(double? amount) {
    if (amount == null) return '-';
    if (amount >= 100000000) return '${(amount / 100000000).toStringAsFixed(2)}亿';
    if (amount >= 10000) return '${(amount / 10000).toStringAsFixed(1)}万';
    return amount.toStringAsFixed(0);
  }
}
