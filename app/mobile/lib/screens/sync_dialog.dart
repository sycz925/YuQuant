import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../config/theme.dart';
import '../providers/sync_provider.dart';
import '../services/data_sync.dart';

class SyncDialog extends StatelessWidget {
  const SyncDialog({super.key});

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<SyncProvider>();
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return AlertDialog(
      title: Row(
        children: [
          const Icon(Icons.sync, size: 22),
          const SizedBox(width: 8),
          const Text('数据同步'),
        ],
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          _buildStep('1. 连接行情服务器', SyncStep.basics, provider, isDark),
          _buildStep('2. 同步ETF/指数基本信息', SyncStep.basics, provider, isDark),
          _buildStep('3. 同步指数日线', SyncStep.indexDaily, provider, isDark),
          _buildStep('4. 同步ETF日线', SyncStep.etfDaily, provider, isDark),
          _buildStep('5. 计算RPS/MA指标', SyncStep.calculate, provider, isDark),
          const SizedBox(height: 16),
          if (provider.running && provider.status.isNotEmpty)
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: isDark ? Colors.white.withOpacity(0.05) : Colors.grey.withOpacity(0.1),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Row(
                children: [
                  const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      provider.status,
                      style: TextStyle(
                        fontSize: 13,
                        color: isDark ? AppColors.darkTextSecondary : AppColors.lightTextSecondary,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          if (provider.error != null)
            Container(
              margin: const EdgeInsets.only(top: 12),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.red.withOpacity(0.1),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.red.withOpacity(0.3)),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(Icons.error_outline, color: Colors.red, size: 18),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      provider.error!,
                      style: const TextStyle(fontSize: 12, color: Colors.red),
                    ),
                  ),
                ],
              ),
            ),
          if (!provider.running && provider.status == '完成')
            Container(
              margin: const EdgeInsets.only(top: 12),
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: Colors.green.withOpacity(0.1),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Row(
                children: [
                  Icon(Icons.check_circle, color: Colors.green, size: 18),
                  SizedBox(width: 8),
                  Text('同步完成!', style: TextStyle(fontSize: 13, color: Colors.green)),
                ],
              ),
            ),
        ],
      ),
      actions: [
        if (!provider.running)
          TextButton(
            onPressed: () => provider.startSync(),
            child: const Text('开始同步'),
          ),
        TextButton(
          onPressed: () {
            if (provider.running) provider.stopSync();
            Navigator.of(context).pop();
          },
          child: Text(provider.running ? '取消' : '关闭'),
        ),
      ],
    );
  }

  Widget _buildStep(String title, SyncStep step, SyncProvider provider, bool isDark) {
    final current = provider.currentStep;
    final stepOrder = SyncStep.values;

    Widget icon;
    if (current == null) {
      icon = Icon(Icons.radio_button_unchecked, size: 18, color: Colors.grey);
    } else if (stepOrder.indexOf(step) < stepOrder.indexOf(current)) {
      icon = const Icon(Icons.check_circle, size: 18, color: Colors.green);
    } else if (step == current && provider.running) {
      icon = const SizedBox(
        width: 18,
        height: 18,
        child: CircularProgressIndicator(strokeWidth: 2),
      );
    } else {
      icon = Icon(Icons.radio_button_unchecked, size: 18, color: Colors.grey);
    }

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        children: [
          icon,
          const SizedBox(width: 10),
          Expanded(
            child: Text(title, style: const TextStyle(fontSize: 13)),
          ),
          if (step == current && provider.total > 0 && provider.running)
            Text(
              '${provider.current}/${provider.total}',
              style: TextStyle(fontSize: 11, color: isDark ? AppColors.darkTextSecondary : AppColors.lightTextSecondary),
            ),
        ],
      ),
    );
  }

  static Future<void> show(BuildContext context) async {
    return showDialog(
      context: context,
      barrierDismissible: false,
      builder: (_) => ChangeNotifierProvider.value(
        value: context.read<SyncProvider>(),
        child: const SyncDialog(),
      ),
    );
  }
}
