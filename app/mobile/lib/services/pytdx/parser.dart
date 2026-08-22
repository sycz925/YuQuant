import 'dart:typed_data';
import 'dart:convert';
import 'protocol.dart';

class TdxParser {
  static int parseCount(Uint8List body) {
    if (body.length < 2) return 0;
    return ByteData.view(body.buffer).getUint16(0, Endian.little);
  }

  static List<Map<String, dynamic>> parseSecurityList(Uint8List body) {
    final result = <Map<String, dynamic>>[];
    const recordSize = 29;
    final bd = ByteData.view(body.buffer);
    int offset = 2; // skip count uint16

    while (offset + recordSize <= body.length) {
      final code = TdxPacket.decodeCode(body.sublist(offset, offset + 6));
      final volunit = bd.getUint16(offset + 6, Endian.little);
      final nameBytes = body.sublist(offset + 8, offset + 16);
      final name = _decodeGbkName(nameBytes);
      final decimalPoint = body[offset + 20];
      final preCloseRaw = bd.getUint32(offset + 21, Endian.little);

      result.add({
        'code': code,
        'name': name,
        'volunit': volunit,
        'decimal_point': decimalPoint,
        'pre_close_raw': preCloseRaw,
      });
      offset += recordSize;
    }
    return result;
  }

  static List<Map<String, dynamic>> parseSecurityBars(Uint8List body, {bool isIndex = false}) {
    final result = <Map<String, dynamic>>[];
    final bd = ByteData.view(body.buffer);
    if (body.length < 2) return result;

    final count = bd.getUint16(0, Endian.little);
    int offset = 2;

    int prevOpen = 0;
    for (int i = 0; i < count; i++) {
      if (offset + 24 > body.length) break;

      final datetime = bd.getUint32(offset, Endian.little);
      final year = (datetime >> 16) & 0x7fff;
      final month = (datetime >> 8) & 0xff;
      final day = datetime & 0xff;
      final tradeDate = '$year${month.toString().padLeft(2, '0')}${day.toString().padLeft(2, '0')}';

      final openDiff = bd.getInt32(offset + 4, Endian.little);
      final closeDiff = bd.getInt32(offset + 8, Endian.little);
      final highDiff = bd.getInt32(offset + 12, Endian.little);
      final lowDiff = bd.getInt32(offset + 16, Endian.little);
      final volume = bd.getUint32(offset + 20, Endian.little);
      final amount = bd.getUint32(offset + 24, Endian.little);

      final open = (prevOpen + openDiff) / 1000.0;
      final close = (open * 1000 + closeDiff) / 1000.0;
      final high = (open * 1000 + highDiff) / 1000.0;
      final low = (open * 1000 + lowDiff) / 1000.0;

      result.add({
        'trade_date': tradeDate,
        'open': open,
        'close': close,
        'high': high,
        'low': low,
        'vol': volume ~/ 100,
        'amount': amount.toDouble(),
      });

      prevOpen = (open * 1000).toInt();
      offset += isIndex ? 28 : 28;
    }
    return result;
  }

  static List<Map<String, dynamic>> parseSecurityQuotes(Uint8List body) {
    final result = <Map<String, dynamic>>[];
    final bd = ByteData.view(body.buffer);
    if (body.length < 2) return result;

    final count = bd.getUint16(0, Endian.little);
    int offset = 2;
    const recordSize = 49;

    for (int i = 0; i < count; i++) {
      if (offset + recordSize > body.length) break;

      final market = body[offset];
      final code = TdxPacket.decodeCode(body.sublist(offset + 1, offset + 7));
      final price = bd.getInt32(offset + 7, Endian.little) / 100.0;
      final preClose = bd.getInt32(offset + 11, Endian.little) / 100.0;
      final open = bd.getInt32(offset + 15, Endian.little) / 100.0;
      final high = bd.getInt32(offset + 19, Endian.little) / 100.0;
      final low = bd.getInt32(offset + 23, Endian.little) / 100.0;
      final vol = bd.getInt32(offset + 27, Endian.little);
      final amount = bd.getInt32(offset + 31, Endian.little).toDouble();

      result.add({
        'market': market,
        'code': code,
        'price': price,
        'pre_close': preClose,
        'open': open,
        'high': high,
        'low': low,
        'vol': vol,
        'amount': amount,
      });
      offset += recordSize;
    }
    return result;
  }

  static List<Map<String, dynamic>> parseXdXrInfo(Uint8List body) {
    final result = <Map<String, dynamic>>[];
    final bd = ByteData.view(body.buffer);
    if (body.length < 2) return result;

    final count = bd.getUint16(0, Endian.little);
    int offset = 2;
    const recordSize = 17;

    for (int i = 0; i < count; i++) {
      if (offset + recordSize > body.length) break;

      final year = bd.getUint16(offset, Endian.little);
      final month = body[offset + 2];
      final day = body[offset + 3];
      final category = body[offset + 4];
      final priceBefora = bd.getInt32(offset + 5, Endian.little) / 1000.0;
      final priceAfter = bd.getInt32(offset + 9, Endian.little) / 1000.0;
      final adjustment = bd.getInt32(offset + 13, Endian.little) / 1000.0;

      result.add({
        'date': '$year${month.toString().padLeft(2, '0')}${day.toString().padLeft(2, '0')}',
        'category': category,
        'price_before': priceBefora,
        'price_after': priceAfter,
        'adjustment': adjustment,
      });
      offset += recordSize;
    }
    return result;
  }

  static String _decodeGbkName(Uint8List bytes) {
    // Simple approach: try to decode as latin1, filter nulls
    final filtered = bytes.where((b) => b != 0).toList();
    if (filtered.isEmpty) return '';
    try {
      return utf8.decode(filtered, allowMalformed: true);
    } catch (_) {
      return String.fromCharCodes(filtered);
    }
  }
}
