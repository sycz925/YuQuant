import 'dart:typed_data';
import 'dart:convert';
import 'dart:developer' as developer;

class TdxPacket {
  static const int magic = 0x010c;

  // Command codes
  static const int cmdGetSecurityCount = 0x0000044e;
  static const int cmdGetSecurityList = 0x00000450;
  static const int cmdGetSecurityBars = 0x01016408;
  static const int cmdGetIndexBars = 0x01016408;
  static const int cmdGetSecurityQuotes = 0x02006320;
  static const int cmdGetXdXrInfo = 0x00000471;

  // K-line categories
  static const int kline5min = 0;
  static const int kline15min = 1;
  static const int kline30min = 2;
  static const int kline60min = 3;
  static const int klineDaily = 4;
  static const int klineWeekly = 5;
  static const int klineMonthly = 6;

  // Markets
  static const int marketSZ = 0;
  static const int marketSH = 1;

  // Setup commands (hex blobs for handshake)
  static final Uint8List setupCmd1 = Uint8List.fromList([
    0x0c, 0x02, 0x18, 0x93, 0x00, 0x01, 0x03, 0x00, 0x03, 0x00, 0x0d, 0x00, 0x01,
  ]);

  static final Uint8List setupCmd2 = Uint8List.fromList([
    0x0c, 0x02, 0x18, 0x94, 0x00, 0x01, 0x03, 0x00, 0x03, 0x00, 0x0d, 0x00, 0x02,
  ]);

  static final Uint8List setupCmd3 = Uint8List.fromList([
    0x0c, 0x03, 0x18, 0x99, 0x00, 0x01, 0x20, 0x00, 0x20, 0x00,
    0xdb, 0x0f, 0xd5, 0xd0, 0xc9, 0xcc, 0xd6, 0xa4, 0xa8, 0xaf, 0x00, 0x00, 0x00,
    0x8f, 0xc2, 0x25, 0x40, 0x13, 0x00, 0x00,
    0xd5, 0x00, 0xc9, 0xcc, 0xbd, 0xf0, 0xd7, 0xea, 0x00, 0x00, 0x00,
    0x02,
  ]);

  static const int headerSize = 16;

  // --- Request Builders ---

  static Uint8List makeGetSecurityCount(int market) {
    final data = Uint8List(18);
    final bd = ByteData.view(data.buffer);
    // Header
    data.setAll(0, [0x0c, 0x0c, 0x18, 0x6c, 0x00, 0x01, 0x08, 0x00, 0x08, 0x00, 0x4e, 0x04]);
    bd.setUint16(12, market, Endian.little);
    data.setAll(14, [0x75, 0xc7, 0x33, 0x01]);
    return data;
  }

  static Uint8List makeGetSecurityList(int market, int start) {
    final data = Uint8List(16);
    final bd = ByteData.view(data.buffer);
    data.setAll(0, [0x0c, 0x01, 0x18, 0x64, 0x01, 0x01, 0x06, 0x00, 0x06, 0x00, 0x50, 0x04]);
    bd.setUint16(12, market, Endian.little);
    bd.setUint16(14, start, Endian.little);
    return data;
  }

  static Uint8List makeGetSecurityBars(int market, String code, int category, int start, int count) {
    final data = Uint8List(36);
    final bd = ByteData.view(data.buffer);
    bd.setUint16(0, magic, Endian.little);
    bd.setUint32(2, cmdGetSecurityBars, Endian.little);
    bd.setUint16(6, 0x001c, Endian.little);
    bd.setUint16(8, 0x001c, Endian.little);
    bd.setUint16(10, 0x052d, Endian.little);
    bd.setUint16(12, market, Endian.little);
    data.setAll(14, _encodeCode(code));
    bd.setUint16(20, category, Endian.little);
    bd.setUint16(22, 1, Endian.little);
    bd.setUint16(24, start, Endian.little);
    bd.setUint16(26, count, Endian.little);
    return data;
  }

  static Uint8List makeGetSecurityQuotes(List<Map<String, dynamic>> stocks) {
    final count = stocks.length;
    final pkgDataLen = 12 + 7 * count;
    final totalLen = 16 + pkgDataLen;
    final data = Uint8List(totalLen);
    final bd = ByteData.view(data.buffer);

    bd.setUint16(0, magic, Endian.little);
    bd.setUint32(2, cmdGetSecurityQuotes, Endian.little);
    bd.setUint32(6, pkgDataLen, Endian.little);
    bd.setUint32(10, pkgDataLen, Endian.little);
    bd.setUint16(14, count, Endian.little);

    int offset = 16;
    for (final stock in stocks) {
      bd.setUint8(offset, stock['market'] as int);
      data.setAll(offset + 1, _encodeCode(stock['code'] as String));
      offset += 7;
    }
    return data;
  }

  static Uint8List makeGetXdXrInfo(int market, String code) {
    final data = Uint8List(24);
    final bd = ByteData.view(data.buffer);
    data.setAll(0, [0x0c, 0x05, 0x18, 0x6f, 0x01, 0x01, 0x10, 0x00, 0x10, 0x00, 0x58, 0x04]);
    bd.setUint16(12, market, Endian.little);
    data.setAll(14, _encodeCode(code));
    bd.setUint16(20, 0, Endian.little);
    bd.setUint16(22, 0xffff, Endian.little);
    return data;
  }

  // --- Response Header Parsing ---

  static Map<String, int> parseHeader(Uint8List headerBytes) {
    if (headerBytes.length < headerSize) {
      throw Exception('Header too short: ${headerBytes.length}');
    }
    final bd = ByteData.view(headerBytes.buffer);
    final result = {
      'field1': bd.getUint32(0, Endian.little),
      'field2': bd.getUint32(4, Endian.little),
      'field3': bd.getUint32(8, Endian.little),
      'zipsize': bd.getUint16(12, Endian.little),
      'unzipsize': bd.getUint16(14, Endian.little),
    };
    developer.log('Header解析: field1=${result['field1']}, field2=${result['field2']}, field3=${result['field3']}, zipsize=${result['zipsize']}, unzipsize=${result['unzipsize']}', name: 'TdxProtocol');
    return result;
  }

  // --- Helpers ---

  static Uint8List _encodeCode(String code) {
    final bytes = Uint8List(6);
    final codeBytes = ascii.encode(code);
    bytes.setAll(0, codeBytes.take(6));
    return bytes;
  }

  static String decodeCode(Uint8List bytes) {
    return ascii.decode(bytes.where((b) => b != 0).toList());
  }

  static String decodeGbk(Uint8List bytes) {
    // Simple GBK decoding for common Chinese chars
    // In production, use a proper GBK decoder package
    try {
      return latin1.decode(bytes.where((b) => b != 0).toList());
    } catch (_) {
      return ascii.decode(bytes.where((b) => b != 0).toList());
    }
  }

  static int decodeVolume(int encoded) {
    return encoded ~/ 100;
  }

  static double decodePrice(int encoded) {
    return encoded / 1000.0;
  }
}
