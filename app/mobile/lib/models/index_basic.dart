class IndexBasic {
  final String code;
  final String name;
  final int? market;
  final String? tdxCode;
  final bool isDisable;
  final double? peTtm;
  final String? updateTime;

  IndexBasic({
    required this.code,
    required this.name,
    this.market,
    this.tdxCode,
    this.isDisable = false,
    this.peTtm,
    this.updateTime,
  });

  factory IndexBasic.fromMap(Map<String, dynamic> map) {
    return IndexBasic(
      code: map['code'] as String,
      name: map['name'] as String,
      market: map['market'] as int?,
      tdxCode: map['tdx_code'] as String?,
      isDisable: (map['is_disable'] as int? ?? 0) == 1,
      peTtm: (map['pe_ttm'] as num?)?.toDouble(),
      updateTime: map['update_time'] as String?,
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'code': code,
      'name': name,
      'market': market,
      'tdx_code': tdxCode,
      'is_disable': isDisable ? 1 : 0,
      'pe_ttm': peTtm,
      'update_time': updateTime,
    };
  }
}
