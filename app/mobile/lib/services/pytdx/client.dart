import 'dart:async';
import 'dart:io';
import 'dart:typed_data';
import 'dart:developer' as developer;
import 'protocol.dart';
import 'parser.dart';
import 'servers.dart';

class TdxClient {
  Socket? _socket;
  int _serverIndex = 0;
  bool _connected = false;
  Uint8List _buffer = Uint8List(0);

  bool get isConnected => _connected;

  void _log(String msg) {
    developer.log(msg, name: 'TdxClient');
    print('[TdxClient] $msg');
  }

  Future<void> connect() async {
    String lastError = '';
    for (int i = 0; i < tdxServers.length; i++) {
      final idx = (_serverIndex + i) % tdxServers.length;
      final server = tdxServers[idx];
      _log('尝试连接 ${server.$1}:${server.$2} (${i + 1}/${tdxServers.length})');
      try {
        _buffer = Uint8List(0);
        _socket = await Socket.connect(server.$1, server.$2, timeout: const Duration(seconds: 8));
        _serverIndex = idx;
        _log('TCP连接成功，开始握手...');
        await _handshake();
        _connected = true;
        _log('握手完成，连接就绪');
        return;
      } catch (e) {
        lastError = '${server.$1}:${server.$2} -> $e';
        _log('连接失败: $lastError');
        continue;
      }
    }
    _log('所有服务器均不可达，最后错误: $lastError');
    throw Exception('无法连接到任何行情服务器: $lastError');
  }

  Future<void> disconnect() async {
    _log('断开连接');
    await _socket?.close();
    _socket = null;
    _connected = false;
    _buffer = Uint8List(0);
  }

  Future<void> _handshake() async {
    _log('发送 setupCmd1...');
    await _sendRaw(TdxPacket.setupCmd1);
    final resp1 = await _readResponse();
    _log('setupCmd1 响应: ${resp1.length} 字节');

    _log('发送 setupCmd2...');
    await _sendRaw(TdxPacket.setupCmd2);
    final resp2 = await _readResponse();
    _log('setupCmd2 响应: ${resp2.length} 字节');

    _log('发送 setupCmd3...');
    await _sendRaw(TdxPacket.setupCmd3);
    final resp3 = await _readResponse();
    _log('setupCmd3 响应: ${resp3.length} 字节');
  }

  Future<void> _sendRaw(Uint8List data) async {
    final hex = data.map((b) => b.toRadixString(16).padLeft(2, '0')).join(' ');
    final hexDisplay = hex.length > 60 ? '${hex.substring(0, 60)}...' : hex;
    _log('发送数据: ${data.length} 字节, hex: $hexDisplay');
    _socket?.add(data);
    await _socket?.flush();
  }

  Future<Uint8List> _sendAndReceive(Uint8List request, String tag) async {
    if (!_connected) {
      _log('$tag: 未连接，尝试重连...');
      await connect();
    }
    try {
      await _sendRaw(request);
      return await _readResponse();
    } catch (e) {
      _log('$tag: 收发失败 -> $e');
      _connected = false;
      rethrow;
    }
  }

  Future<Uint8List> _readResponse() async {
    _log('等待响应头 (${TdxPacket.headerSize} 字节), 缓冲区: ${_buffer.length} 字节');
    final headerBytes = await _readExact(TdxPacket.headerSize);
    _log('收到头部: ${headerBytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join(' ')}');
    final header = TdxPacket.parseHeader(headerBytes);
    final zipsize = header['zipsize']!;
    final unzipsize = header['unzipsize']!;
    _log('解析头部: zipsize=$zipsize, unzipsize=$unzipsize');

    var body = await _readExact(zipsize);

    if (zipsize != unzipsize) {
      _log('解压数据: $zipsize -> $unzipsize');
      body = Uint8List.fromList(zlib.decode(body));
    }
    _log('响应体: ${body.length} 字节');
    return body;
  }

  Future<Uint8List> _readExact(int count) async {
    // 先从缓冲区取数据
    if (_buffer.length >= count) {
      final result = _buffer.sublist(0, count);
      _buffer = _buffer.sublist(count);
      _log('从缓冲区读取: ${result.length} 字节, 剩余缓冲: ${_buffer.length} 字节');
      return result;
    }

    // 缓冲区不够，从 socket 继续读
    final data = BytesBuilder();
    data.add(_buffer);
    int received = _buffer.length;
    _buffer = Uint8List(0);
    _log('缓冲区不足 ($received/$count), 从socket继续读...');

    final completer = Completer<Uint8List>();
    late StreamSubscription<List<int>> sub;
    sub = _socket!.listen(
      (chunk) {
        data.add(chunk);
        received += chunk.length;
        _log('接收数据: +${chunk.length} 字节, 累计 $received/$count');
        if (received >= count) {
          final allData = data.takeBytes();
          // 保存多余数据到缓冲区
          if (allData.length > count) {
            _buffer = allData.sublist(count);
            _log('保存到缓冲区: ${_buffer.length} 字节');
          }
          if (!completer.isCompleted) {
            completer.complete(allData.sublist(0, count));
          }
          sub.cancel();
        }
      },
      onError: (e) {
        _log('Socket错误: $e');
        if (!completer.isCompleted) completer.completeError(e);
      },
      onDone: () {
        _log('Socket关闭, 已接收 $received/$count 字节');
        if (!completer.isCompleted) {
          if (received >= count) {
            final allData = data.takeBytes();
            if (allData.length > count) {
              _buffer = allData.sublist(count);
            }
            completer.complete(allData.sublist(0, count));
          } else {
            completer.completeError(Exception('连接提前关闭: 收到 $received/$count 字节'));
          }
        }
      },
    );

    return completer.future.timeout(const Duration(seconds: 10), onTimeout: () {
      sub.cancel();
      throw TimeoutException('读取超时: 已收到 $received/$count 字节');
    });
  }

  Future<int> getSecurityCount(int market) async {
    final request = TdxPacket.makeGetSecurityCount(market);
    final body = await _sendAndReceive(request, 'getSecurityCount');
    return TdxParser.parseCount(body);
  }

  Future<List<Map<String, dynamic>>> getSecurityList(int market, int start) async {
    final request = TdxPacket.makeGetSecurityList(market, start);
    final body = await _sendAndReceive(request, 'getSecurityList');
    return TdxParser.parseSecurityList(body);
  }

  Future<List<Map<String, dynamic>>> getSecurityBars(
    int market, String code, int category, int start, int count,
  ) async {
    final request = TdxPacket.makeGetSecurityBars(market, code, category, start, count);
    final body = await _sendAndReceive(request, 'getSecurityBars($code)');
    return TdxParser.parseSecurityBars(body);
  }

  Future<List<Map<String, dynamic>>> getSecurityQuotes(List<Map<String, dynamic>> stocks) async {
    final request = TdxPacket.makeGetSecurityQuotes(stocks);
    final body = await _sendAndReceive(request, 'getSecurityQuotes');
    return TdxParser.parseSecurityQuotes(body);
  }

  Future<List<Map<String, dynamic>>> getXdXrInfo(int market, String code) async {
    final request = TdxPacket.makeGetXdXrInfo(market, code);
    final body = await _sendAndReceive(request, 'getXdXrInfo');
    return TdxParser.parseXdXrInfo(body);
  }
}
