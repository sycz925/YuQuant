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

    if (provider.error != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('同步失败: ${provider.error}'), backgroundColor: Colors.red),
        );
        provider.clearError();
      });
    }

    if (!provider.running && provider.currentStep == null && provider.status == '完成') {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('同步完成!'), backgroundColor: Colors.green),
        );
        provider.clearError();
      });
    }

    return AlertDialog(
      title: const Text('数据同步'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          _buildStep('1. 同步基本信息', SyncStep.basics, provider, isDark),
          _buildStep('2. 同步指数日线', SyncStep.indexDaily, provider, isDark),
          _buildStep('3. 同步ETF日线', SyncStep.etfDaily, provider, isDark),
          _buildStep('4. 计算RPS/MA', SyncStep.calculate, provider, isDark),
          const SizedBox(height: 16),
          if (provider.currentStep != null && provider.running)
            Text(
              '${provider.currentName} ${provider.status}',
              style: TextStyle(fontSize: 12, color: isDark ? AppColors.darkTextSecondary : AppColors.lightTextSecondary),
            ),
          if (provider.status == '完成' && !provider.running)
            const Text('✅ 同步完成', style: TextStyle(color: Colors.green, fontSize: 14)),
          if (provider.status == '失败')
            const Text('❌ 同步失败', style: TextStyle(color: Colors.red, fontSize: 14)),
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
      icon = const Icon(Icons.hourglass_empty, size: 20, color: Colors.grey);
    } else if (stepOrder.indexOf(step) < stepOrder.indexOf(current)) {
      icon = Icon(Icons.check_circle, size: 20, color: AppColors.rise);
    } else if (step == current) {
      icon = const SizedBox(
        width: 20,
        height: 20,
        child: CircularProgressIndicator(strokeWidth: 2),
      );
    } else {
      icon = const Icon(Icons.hourglass_empty, size: 20, color: Colors.grey);
    }

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          icon,
          const SizedBox(width: 12),
          Expanded(
            child: Text(title, style: const TextStyle(fontSize: 14)),
          ),
          if (step == current && provider.total > 0)
            Text(
              '${provider.current}/${provider.total}',
              style: TextStyle(fontSize: 12, color: isDark ? AppColors.darkTextSecondary : AppColors.lightTextSecondary),
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
