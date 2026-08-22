import 'dart:async';
import 'database.dart';
import 'pytdx/client.dart';
import 'pytdx/protocol.dart';
import 'rps_calculator.dart';
import '../models/etf_basic.dart';
import '../models/daily_bar.dart';
import '../models/index_basic.dart';

enum SyncStep { basics, indexDaily, etfDaily, calculate }

class SyncProgress {
  final SyncStep step;
  final int current;
  final int total;
  final String status;

  SyncProgress({required this.step, this.current = 0, this.total = 0, this.status = 'running'});
}

class DataSyncService {
  final TdxClient _client = TdxClient();
  final DatabaseHelper _db = DatabaseHelper.instance;

  Future<void> syncAll({
    Function(SyncProgress)? onProgress,
  }) async {
    try {
      await _client.connect();

      // Step 1: Sync basics
      onProgress?.call(SyncProgress(step: SyncStep.basics, status: 'running'));
      await _syncBasics(onProgress);

      // Step 2: Sync index daily
      onProgress?.call(SyncProgress(step: SyncStep.indexDaily, status: 'running'));
      await _syncIndexDaily(onProgress);

      // Step 3: Sync ETF daily
      onProgress?.call(SyncProgress(step: SyncStep.etfDaily, status: 'running'));
      await _syncEtfDaily(onProgress);

      // Step 4: Calculate indicators
      onProgress?.call(SyncProgress(step: SyncStep.calculate, status: 'running'));
      await _calculateIndicators(onProgress);

      onProgress?.call(SyncProgress(step: SyncStep.calculate, status: 'completed'));
    } finally {
      await _client.disconnect();
    }
  }

  Future<void> _syncBasics(Function(SyncProgress)? onProgress) async {
    // Sync ETF basics
    final etfList = <EtfBasic>[];
    int start = 0;
    while (true) {
      final items = await _client.getSecurityList(TdxPacket.marketSH, start);
      if (items.isEmpty) break;
      for (final item in items) {
        final code = item['code'] as String;
        if (code.startsWith('5') || code.startsWith('1')) {
          etfList.add(EtfBasic(code: code, name: item['name'] as String));
        }
      }
      start += items.length;
      if (items.length < 1000) break;
    }

    // Also check Shenzhen
    start = 0;
    while (true) {
      final items = await _client.getSecurityList(TdxPacket.marketSZ, start);
      if (items.isEmpty) break;
      for (final item in items) {
        final code = item['code'] as String;
        if (code.startsWith('1') || code.startsWith('5')) {
          etfList.add(EtfBasic(code: code, name: item['name'] as String));
        }
      }
      start += items.length;
      if (items.length < 1000) break;
    }

    await _db.bulkUpsertEtfBasics(etfList);

    // Sync index basics (hardcoded for now)
    final indexList = [
      IndexBasic(code: '000001', name: '上证指数', market: 1),
      IndexBasic(code: '399001', name: '深证成指', market: 0),
      IndexBasic(code: '399006', name: '创业板指', market: 0),
      IndexBasic(code: '000300', name: '沪深300', market: 1),
      IndexBasic(code: '000905', name: '中证500', market: 1),
      IndexBasic(code: '000852', name: '中证1000', market: 1),
    ];
    await _db.bulkUpsertIndexBasics(indexList);

    onProgress?.call(SyncProgress(step: SyncStep.basics, current: 1, total: 1, status: 'completed'));
  }

  Future<void> _syncIndexDaily(Function(SyncProgress)? onProgress) async {
    final indices = await _db.getIndexBasics(enabledOnly: true);
    for (int i = 0; i < indices.length; i++) {
      final idx = indices[i];
      final market = idx.market ?? (idx.code.startsWith('6') || idx.code.startsWith('000') ? 1 : 0);
      final bars = await _client.getSecurityBars(market, idx.code, TdxPacket.klineDaily, 0, 250);
      final dailyBars = bars.map((b) => DailyBar(
        stockCode: idx.code,
        tradeDate: b['trade_date'] as String,
        open: b['open'] as double?,
        high: b['high'] as double?,
        low: b['low'] as double?,
        close: b['close'] as double?,
        vol: (b['vol'] as int?)?.toDouble(),
        amount: b['amount'] as double?,
        dataSource: 'pytdx',
        isFinal: true,
      )).toList();
      await _db.upsertDailyBars('index', dailyBars);
      onProgress?.call(SyncProgress(step: SyncStep.indexDaily, current: i + 1, total: indices.length));
    }
    onProgress?.call(SyncProgress(step: SyncStep.indexDaily, current: indices.length, total: indices.length, status: 'completed'));
  }

  Future<void> _syncEtfDaily(Function(SyncProgress)? onProgress) async {
    final etfs = await _db.getEtfBasics();
    for (int i = 0; i < etfs.length; i++) {
      final etf = etfs[i];
      final market = etf.code.startsWith('5') || etf.code.startsWith('6') ? TdxPacket.marketSH : TdxPacket.marketSZ;
      try {
        final bars = await _client.getSecurityBars(market, etf.code, TdxPacket.klineDaily, 0, 250);
        final dailyBars = bars.map((b) => DailyBar(
          stockCode: etf.code,
          tradeDate: b['trade_date'] as String,
          open: b['open'] as double?,
          high: b['high'] as double?,
          low: b['low'] as double?,
          close: b['close'] as double?,
          vol: (b['vol'] as int?)?.toDouble(),
          amount: b['amount'] as double?,
          dataSource: 'pytdx',
          isFinal: true,
        )).toList();
        await _db.upsertDailyBars('etf', dailyBars);
      } catch (_) {}
      onProgress?.call(SyncProgress(step: SyncStep.etfDaily, current: i + 1, total: etfs.length));
    }
    onProgress?.call(SyncProgress(step: SyncStep.etfDaily, current: etfs.length, total: etfs.length, status: 'completed'));
  }

  Future<void> _calculateIndicators(Function(SyncProgress)? onProgress) async {
    final bars = await _db.getAllLatestDailyBars('etf');
    if (bars.isEmpty) return;

    // Calculate RPS for each period
    for (final period in [10, 20, 50, 120]) {
      final allReturns = bars.where((b) => true).map((b) {
        switch (period) {
          case 10: return b.chg10d ?? 0.0;
          case 20: return b.chg20d ?? 0.0;
          case 50: return b.chg50d ?? 0.0;
          case 120: return b.chg120d ?? 0.0;
          default: return 0.0;
        }
      }).toList();

      for (final bar in bars) {
        final targetReturn = (() {
          switch (period) {
            case 10: return bar.chg10d;
            case 20: return bar.chg20d;
            case 50: return bar.chg50d;
            case 120: return bar.chg120d;
            default: return null;
          }
        })();

        if (targetReturn != null) {
          final rps = RpsCalculator.calculateRps(allReturns, targetReturn);
          await _db.updateRps('etf', bar.stockCode, bar.tradeDate, {'rps_$period': rps});
        }
      }
    }
    onProgress?.call(SyncProgress(step: SyncStep.calculate, current: 1, total: 1, status: 'completed'));
  }
}
