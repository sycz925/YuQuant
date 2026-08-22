import 'dart:async';
import 'dart:io';
import 'dart:typed_data';
import 'protocol.dart';
import 'parser.dart';
import 'servers.dart';

class TdxClient {
  Socket? _socket;
  int _serverIndex = 0;
  bool _connected = false;

  bool get isConnected => _connected;

  Future<void> connect() async {
    for (int i = 0; i < tdxServers.length; i++) {
      final idx = (_serverIndex + i) % tdxServers.length;
      final server = tdxServers[idx];
      try {
        _socket = await Socket.connect(server.$1, server.$2, timeout: const Duration(seconds: 5));
        _serverIndex = idx;
        await _handshake();
        _connected = true;
        return;
      } catch (_) {
        continue;
      }
    }
    throw Exception('Failed to connect to any TDX server');
  }

  Future<void> disconnect() async {
    await _socket?.close();
    _socket = null;
    _connected = false;
  }

  Future<void> _handshake() async {
    await _sendRaw(TdxPacket.setupCmd1);
    await _readResponse();
    await _sendRaw(TdxPacket.setupCmd2);
    await _readResponse();
    await _sendRaw(TdxPacket.setupCmd3);
    await _readResponse();
  }

  Future<void> _sendRaw(Uint8List data) async {
    _socket?.add(data);
    await _socket?.flush();
  }

  Future<Uint8List> _sendAndReceive(Uint8List request) async {
    if (!_connected) await connect();
    try {
      await _sendRaw(request);
      return await _readResponse();
    } catch (e) {
      _connected = false;
      rethrow;
    }
  }

  Future<Uint8List> _readResponse() async {
    final headerBytes = await _readExact(TdxPacket.headerSize);
    final header = TdxPacket.parseHeader(headerBytes);
    final zipsize = header['zipsize']!;
    final unzipsize = header['unzipsize']!;

    var body = await _readExact(zipsize);

    if (zipsize != unzipsize) {
      body = Uint8List.fromList(zlib.decode(body));
    }
    return body;
  }

  Future<Uint8List> _readExact(int count) async {
    final completer = Completer<Uint8List>();
    final data = BytesBuilder();
    int received = 0;

    late StreamSubscription<List<int>> sub;
    sub = _socket!.listen((chunk) {
      data.add(chunk);
      received += chunk.length;
      if (received >= count) {
        completer.complete(data.takeBytes());
        sub.cancel();
      }
    });

    return completer.future.timeout(const Duration(seconds: 5), onTimeout: () {
      sub.cancel();
      throw TimeoutException('Read timeout');
    });
  }

  Future<int> getSecurityCount(int market) async {
    final request = TdxPacket.makeGetSecurityCount(market);
    final body = await _sendAndReceive(request);
    return TdxParser.parseCount(body);
  }

  Future<List<Map<String, dynamic>>> getSecurityList(int market, int start) async {
    final request = TdxPacket.makeGetSecurityList(market, start);
    final body = await _sendAndReceive(request);
    return TdxParser.parseSecurityList(body);
  }

  Future<List<Map<String, dynamic>>> getSecurityBars(
    int market, String code, int category, int start, int count,
  ) async {
    final request = TdxPacket.makeGetSecurityBars(market, code, category, start, count);
    final body = await _sendAndReceive(request);
    return TdxParser.parseSecurityBars(body);
  }

  Future<List<Map<String, dynamic>>> getSecurityQuotes(List<Map<String, dynamic>> stocks) async {
    final request = TdxPacket.makeGetSecurityQuotes(stocks);
    final body = await _sendAndReceive(request);
    return TdxParser.parseSecurityQuotes(body);
  }

  Future<List<Map<String, dynamic>>> getXdXrInfo(int market, String code) async {
    final request = TdxPacket.makeGetXdXrInfo(market, code);
    final body = await _sendAndReceive(request);
    return TdxParser.parseXdXrInfo(body);
  }

}
