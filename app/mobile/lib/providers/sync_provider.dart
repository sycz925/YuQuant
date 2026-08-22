import 'package:flutter/material.dart';
import '../services/data_sync.dart';

class SyncProvider extends ChangeNotifier {
  final DataSyncService _sync = DataSyncService();
  SyncStep? _currentStep;
  String _status = '';
  int _current = 0;
  int _total = 0;
  bool _running = false;

  SyncStep? get currentStep => _currentStep;
  String get status => _status;
  int get current => _current;
  int get total => _total;
  bool get running => _running;

  String get currentName {
    switch (_currentStep) {
      case SyncStep.basics: return '基本信息';
      case SyncStep.indexDaily: return '指数日线';
      case SyncStep.etfDaily: return 'ETF日线';
      case SyncStep.calculate: return '计算指标';
      default: return '准备中';
    }
  }

  Future<void> startSync() async {
    if (_running) return;
    _running = true;
    notifyListeners();

    try {
      await _sync.sync((step, current, total, status) {
        _currentStep = step;
        _current = current;
        _total = total;
        _status = status;
        notifyListeners();
      });
    } finally {
      _running = false;
      _currentStep = null;
      _status = '完成';
      notifyListeners();
    }
  }

  void stopSync() {
    _sync.stop();
    _running = false;
    _currentStep = null;
    _status = '已停止';
    notifyListeners();
  }
}
