class WatchlistItem {
  final String code;
  final String type;
  final String createdAt;
  final String? tdxStatus;

  WatchlistItem({
    required this.code,
    required this.type,
    required this.createdAt,
    this.tdxStatus,
  });

  factory WatchlistItem.fromMap(Map<String, dynamic> map) {
    return WatchlistItem(
      code: map['code'] as String,
      type: map['type'] as String,
      createdAt: map['created_at'] as String,
      tdxStatus: map['tdx_status'] as String?,
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'code': code,
      'type': type,
      'created_at': createdAt,
      'tdx_status': tdxStatus,
    };
  }
}
