class DailyBar {
  final String stockCode;
  final String tradeDate;
  final double? open, high, low, close;
  final double? vol, amount;
  final double? chgPct;
  final String? dataSource;
  final bool isFinal;
  final double? ma10, ma20, ma50, ma120;
  final double? volMa5, volMa10, volMa20, volMa50;
  final double? chg5d, chg10d, chg20d, chg50d, chg120d, chg250d;
  final double? rps10, rps20, rps50, rps120;
  final double? closeRaw;
  final String? updateTime;

  DailyBar({
    required this.stockCode,
    required this.tradeDate,
    this.open, this.high, this.low, this.close,
    this.vol, this.amount, this.chgPct,
    this.dataSource, this.isFinal = false,
    this.ma10, this.ma20, this.ma50, this.ma120,
    this.volMa5, this.volMa10, this.volMa20, this.volMa50,
    this.chg5d, this.chg10d, this.chg20d, this.chg50d, this.chg120d, this.chg250d,
    this.rps10, this.rps20, this.rps50, this.rps120,
    this.closeRaw, this.updateTime,
  });

  factory DailyBar.fromMap(Map<String, dynamic> map) {
    return DailyBar(
      stockCode: map['stock_code'] as String,
      tradeDate: map['trade_date'] as String,
      open: (map['open'] as num?)?.toDouble(),
      high: (map['high'] as num?)?.toDouble(),
      low: (map['low'] as num?)?.toDouble(),
      close: (map['close'] as num?)?.toDouble(),
      vol: (map['vol'] as num?)?.toDouble(),
      amount: (map['amount'] as num?)?.toDouble(),
      chgPct: (map['chg_pct'] as num?)?.toDouble(),
      dataSource: map['data_source'] as String?,
      isFinal: (map['is_final'] as int? ?? 0) == 1,
      ma10: (map['ma10'] as num?)?.toDouble(),
      ma20: (map['ma20'] as num?)?.toDouble(),
      ma50: (map['ma50'] as num?)?.toDouble(),
      ma120: (map['ma120'] as num?)?.toDouble(),
      volMa5: (map['vol_ma5'] as num?)?.toDouble(),
      volMa10: (map['vol_ma10'] as num?)?.toDouble(),
      volMa20: (map['vol_ma20'] as num?)?.toDouble(),
      volMa50: (map['vol_ma50'] as num?)?.toDouble(),
      chg5d: (map['chg_5d'] as num?)?.toDouble(),
      chg10d: (map['chg_10d'] as num?)?.toDouble(),
      chg20d: (map['chg_20d'] as num?)?.toDouble(),
      chg50d: (map['chg_50d'] as num?)?.toDouble(),
      chg120d: (map['chg_120d'] as num?)?.toDouble(),
      chg250d: (map['chg_250d'] as num?)?.toDouble(),
      rps10: (map['rps_10'] as num?)?.toDouble(),
      rps20: (map['rps_20'] as num?)?.toDouble(),
      rps50: (map['rps_50'] as num?)?.toDouble(),
      rps120: (map['rps_120'] as num?)?.toDouble(),
      closeRaw: (map['close_raw'] as num?)?.toDouble(),
      updateTime: map['update_time'] as String?,
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'stock_code': stockCode,
      'trade_date': tradeDate,
      'open': open, 'high': high, 'low': low, 'close': close,
      'vol': vol, 'amount': amount, 'chg_pct': chgPct,
      'data_source': dataSource, 'is_final': isFinal ? 1 : 0,
      'ma10': ma10, 'ma20': ma20, 'ma50': ma50, 'ma120': ma120,
      'vol_ma5': volMa5, 'vol_ma10': volMa10, 'vol_ma20': volMa20, 'vol_ma50': volMa50,
      'chg_5d': chg5d, 'chg_10d': chg10d, 'chg_20d': chg20d,
      'chg_50d': chg50d, 'chg_120d': chg120d, 'chg_250d': chg250d,
      'rps_10': rps10, 'rps_20': rps20, 'rps_50': rps50, 'rps_120': rps120,
      'close_raw': closeRaw, 'update_time': updateTime,
    };
  }
}
