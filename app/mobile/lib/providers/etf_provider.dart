import 'package:flutter/material.dart';
import '../services/database.dart';
import '../models/daily_bar.dart';
import '../models/etf_basic.dart';

class EtfProvider extends ChangeNotifier {
  final DatabaseHelper _db = DatabaseHelper.instance;
  List<DailyBar> _bars = [];
  List<EtfBasic> _basics = [];
  String _searchQuery = '';
  String _sortField = 'rps_10';
  bool _sortAscending = false;
  int _redFilter = 0;

  List<DailyBar> get bars {
    var filtered = _bars.where((b) {
      if (_searchQuery.isEmpty) return true;
      final basic = _basics.firstWhere((e) => e.code == b.stockCode, orElse: () => EtfBasic(code: '', name: ''));
      return basic.code.contains(_searchQuery) || basic.name.contains(_searchQuery);
    }).toList();

    if (_redFilter > 0) {
      filtered = filtered.where((b) {
        int count = 0;
        if ((b.rps10 ?? 0) > 87) count++;
        if ((b.rps50 ?? 0) > 87) count++;
        if ((b.rps120 ?? 0) > 87) count++;
        return count >= _redFilter;
      }).toList();
    }

    filtered.sort((a, b) {
      final aVal = _getSortValue(a);
      final bVal = _getSortValue(b);
      final cmp = (aVal ?? 0).compareTo(bVal ?? 0);
      return _sortAscending ? cmp : -cmp;
    });

    return filtered;
  }

  String get searchQuery => _searchQuery;
  String get sortField => _sortField;
  bool get sortAscending => _sortAscending;
  int get redFilter => _redFilter;
  int get totalCount => _bars.length;

  double? _getSortValue(DailyBar bar) {
    switch (_sortField) {
      case 'code': return double.tryParse(bar.stockCode);
      case 'close': return bar.close;
      case 'chg_pct': return bar.chgPct;
      case 'rps_10': return bar.rps10;
      case 'rps_50': return bar.rps50;
      case 'rps_120': return bar.rps120;
      case 'chg_5d': return bar.chg5d;
      case 'chg_10d': return bar.chg10d;
      default: return bar.rps10;
    }
  }

  Future<void> loadData() async {
    _basics = await _db.getEtfBasics();
    _bars = await _db.getAllLatestDailyBars('etf');
    notifyListeners();
  }

  void setSearch(String query) {
    _searchQuery = query;
    notifyListeners();
  }

  void setSort(String field) {
    if (_sortField == field) {
      _sortAscending = !_sortAscending;
    } else {
      _sortField = field;
      _sortAscending = false;
    }
    notifyListeners();
  }

  void setRedFilter(int filter) {
    _redFilter = filter;
    notifyListeners();
  }

  String getName(String code) {
    final basic = _basics.firstWhere((e) => e.code == code, orElse: () => EtfBasic(code: code, name: code));
    return basic.name;
  }
}
