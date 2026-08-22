class EtfBasic {
  final String code;
  final String name;
  final String? updateTime;

  EtfBasic({required this.code, required this.name, this.updateTime});

  factory EtfBasic.fromMap(Map<String, dynamic> map) {
    return EtfBasic(
      code: map['code'] as String,
      name: map['name'] as String,
      updateTime: map['update_time'] as String?,
    );
  }

  Map<String, dynamic> toMap() {
    return {
      'code': code,
      'name': name,
      'update_time': updateTime,
    };
  }
}
