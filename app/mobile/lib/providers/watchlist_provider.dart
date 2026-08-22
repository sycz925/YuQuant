import 'package:flutter/material.dart';
import '../services/database.dart';
import '../models/watchlist_item.dart';

class WatchlistProvider extends ChangeNotifier {
  final DatabaseHelper _db = DatabaseHelper.instance;
  List<WatchlistItem> _items = [];

  List<WatchlistItem> get items => _items;

  Future<void> loadData() async {
    _items = await _db.getWatchlist();
    notifyListeners();
  }

  Future<void> add(String code, String type) async {
    final item = WatchlistItem(
      code: code,
      type: type,
      createdAt: DateTime.now().toIso8601String(),
    );
    await _db.addWatchlist(item);
    await loadData();
  }

  Future<void> remove(String code) async {
    await _db.removeWatchlist(code);
    await loadData();
  }

  Future<bool> isInWatchlist(String code) async {
    return await _db.isInWatchlist(code);
  }
}
