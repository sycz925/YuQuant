class EtfAlert {
  final String code;
  final String? name;
  final String tradeDate;
  final double? close;
  final double? closeRaw;
  final double? amount;
  final double? chgPct;
  final double? eneMa;
  final double? eneUpper;
  final double? eneLower;
  final String reason;
  final String? createdAt;

  EtfAlert({
    required this.code,
    this.name,
    required this.tradeDate,
    this.close,
    this.closeRaw,
    this.amount,
    this.chgPct,
    this.eneMa,
    this.eneUpper,
    this.eneLower,
    required this.reason,
    this.createdAt,
  });

  factory EtfAlert.fromMap(Map<String, dynamic> map) {
    return EtfAlert(
      code: map['code'] as String,
      name: map['name'] as String?,
      tradeDate: map['trade_date'] as String,
      close: (map['close'] as num?)?.toDouble(),
      closeRaw: (map['close_raw'] as num?)?.toDouble(),
      amount: (map['amount'] as num?)?.toDouble(),
      chgPct: (map['chg_pct'] as num?)?.toDouble(),
      eneMa: (map['ene_ma'] as num?)?.toDouble(),
      eneUpper: (map['ene_upper'] as num?)?.toDouble(),
      eneLower: (map['ene_lower'] as num?)?.toDouble(),
      reason: map['reason'] as String,
      createdAt: map['created_at'] as String?,
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'code': code,
      'name': name,
      'trade_date': tradeDate,
      'close': close,
      'close_raw': closeRaw,
      'amount': amount,
      'chg_pct': chgPct,
      'ene_ma': eneMa,
      'ene_upper': eneUpper,
      'ene_lower': eneLower,
      'reason': reason,
      'created_at': createdAt,
    };
  }
}
