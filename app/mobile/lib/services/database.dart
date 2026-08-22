import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart';
import '../models/etf_basic.dart';
import '../models/daily_bar.dart';
import '../models/index_basic.dart';
import '../models/etf_alert.dart';
import '../models/watchlist_item.dart';

class DatabaseHelper {
  static final DatabaseHelper instance = DatabaseHelper._();
  static Database? _database;

  DatabaseHelper._();

  Future<Database> get database async {
    if (_database != null) return _database!;
    _database = await _initDatabase();
    return _database!;
  }

  Future<Database> _initDatabase() async {
    final path = join(await getDatabasesPath(), 'yuquant.db');
    return await openDatabase(path, version: 1, onCreate: _onCreate);
  }

  Future<void> _onCreate(Database db, int version) async {
    await db.execute('''
      CREATE TABLE etf_basics (
        code TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        update_time TEXT
      )
    ''');

    await db.execute('''
      CREATE TABLE etf_daily (
        stock_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        open REAL, high REAL, low REAL, close REAL,
        vol REAL, amount REAL, chg_pct REAL,
        data_source TEXT, is_final INTEGER DEFAULT 0,
        ma10 REAL, ma20 REAL, ma50 REAL, ma120 REAL,
        vol_ma5 REAL, vol_ma10 REAL, vol_ma20 REAL, vol_ma50 REAL,
        chg_5d REAL, chg_10d REAL, chg_20d REAL, chg_50d REAL, chg_120d REAL, chg_250d REAL,
        rps_10 REAL, rps_20 REAL, rps_50 REAL, rps_120 REAL,
        close_raw REAL, update_time TEXT,
        PRIMARY KEY (stock_code, trade_date)
      )
    ''');
    await db.execute('CREATE INDEX idx_etf_daily_date ON etf_daily(trade_date)');

    await db.execute('''
      CREATE TABLE index_basics (
        code TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        market INTEGER, tdx_code TEXT,
        is_disable INTEGER DEFAULT 0,
        pe_ttm REAL, update_time TEXT
      )
    ''');

    await db.execute('''
      CREATE TABLE index_daily (
        stock_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        open REAL, high REAL, low REAL, close REAL,
        volume REAL, amount REAL, chg_pct REAL,
        pe_ttm REAL, data_source TEXT, is_final INTEGER DEFAULT 0,
        update_time TEXT,
        PRIMARY KEY (stock_code, trade_date)
      )
    ''');
    await db.execute('CREATE INDEX idx_index_daily_date ON index_daily(trade_date)');

    await db.execute('''
      CREATE TABLE etf_alerts (
        code TEXT NOT NULL, name TEXT,
        trade_date TEXT NOT NULL,
        close REAL, close_raw REAL, amount REAL, chg_pct REAL,
        ene_ma REAL, ene_upper REAL, ene_lower REAL,
        reason TEXT NOT NULL, created_at TEXT,
        PRIMARY KEY (code, trade_date, reason)
      )
    ''');

    await db.execute('''
      CREATE TABLE watchlist (
        code TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        created_at TEXT NOT NULL,
        tdx_status TEXT
      )
    ''');

    await db.execute('''
      CREATE TABLE sync_tasks (
        task_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        sources TEXT, message TEXT, error TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
      )
    ''');
  }

  // --- etf_basics ---
  Future<void> bulkUpsertEtfBasics(List<EtfBasic> list) async {
    final db = await database;
    final batch = db.batch();
    for (final e in list) {
      batch.insert('etf_basics', e.toMap(), conflictAlgorithm: ConflictAlgorithm.replace);
    }
    await batch.commit(noResult: true);
  }

  Future<List<EtfBasic>> getEtfBasics() async {
    final db = await database;
    final rows = await db.query('etf_basics');
    return rows.map((r) => EtfBasic.fromMap(r)).toList();
  }

  // --- etf_daily ---
  Future<void> upsertDailyBars(String type, List<DailyBar> bars) async {
    final db = await database;
    final table = type == 'etf' ? 'etf_daily' : 'index_daily';
    final batch = db.batch();
    for (final b in bars) {
      batch.insert(table, b.toMap(), conflictAlgorithm: ConflictAlgorithm.replace);
    }
    await batch.commit(noResult: true);
  }

  Future<List<DailyBar>> getDailyBars(String type, String code, {int limit = 250}) async {
    final db = await database;
    final table = type == 'etf' ? 'etf_daily' : 'index_daily';
    final rows = await db.query(table, where: 'stock_code = ?', whereArgs: [code], orderBy: 'trade_date DESC', limit: limit);
    return rows.map((r) => DailyBar.fromMap(r)).toList();
  }

  Future<DailyBar?> getLatestDailyBar(String type, String code) async {
    final db = await database;
    final table = type == 'etf' ? 'etf_daily' : 'index_daily';
    final rows = await db.query(table, where: 'stock_code = ?', whereArgs: [code], orderBy: 'trade_date DESC', limit: 1);
    return rows.isEmpty ? null : DailyBar.fromMap(rows.first);
  }

  Future<List<DailyBar>> getAllLatestDailyBars(String type) async {
    final db = await database;
    final table = type == 'etf' ? 'etf_daily' : 'index_daily';
    final rows = await db.rawQuery('''
      SELECT d.* FROM $table d
      INNER JOIN (SELECT stock_code, MAX(trade_date) as max_date FROM $table GROUP BY stock_code) m
      ON d.stock_code = m.stock_code AND d.trade_date = m.max_date
    ''');
    return rows.map((r) => DailyBar.fromMap(r)).toList();
  }

  Future<void> updateRps(String type, String code, String date, Map<String, double> rps) async {
    final db = await database;
    final table = type == 'etf' ? 'etf_daily' : 'index_daily';
    await db.update(table, rps.map((k, v) => MapEntry(k, v)), where: 'stock_code = ? AND trade_date = ?', whereArgs: [code, date]);
  }

  Future<void> updateIndicators(String type, String code, String date, Map<String, double?> indicators) async {
    final db = await database;
    final table = type == 'etf' ? 'etf_daily' : 'index_daily';
    await db.update(table, indicators, where: 'stock_code = ? AND trade_date = ?', whereArgs: [code, date]);
  }

  // --- index_basics ---
  Future<void> bulkUpsertIndexBasics(List<IndexBasic> list) async {
    final db = await database;
    final batch = db.batch();
    for (final e in list) {
      batch.insert('index_basics', e.toMap(), conflictAlgorithm: ConflictAlgorithm.replace);
    }
    await batch.commit(noResult: true);
  }

  Future<List<IndexBasic>> getIndexBasics({bool enabledOnly = false}) async {
    final db = await database;
    final where = enabledOnly ? 'is_disable = 0' : null;
    final rows = await db.query('index_basics', where: where);
    return rows.map((r) => IndexBasic.fromMap(r)).toList();
  }

  // --- etf_alerts ---
  Future<void> upsertAlerts(List<EtfAlert> alerts) async {
    final db = await database;
    final batch = db.batch();
    for (final a in alerts) {
      batch.insert('etf_alerts', a.toMap(), conflictAlgorithm: ConflictAlgorithm.replace);
    }
    await batch.commit(noResult: true);
  }

  Future<List<EtfAlert>> getAlerts({String? code, int limit = 50}) async {
    final db = await database;
    final where = code != null ? 'code = ?' : null;
    final whereArgs = code != null ? [code] : null;
    final rows = await db.query('etf_alerts', where: where, whereArgs: whereArgs, orderBy: 'trade_date DESC', limit: limit);
    return rows.map((r) => EtfAlert.fromMap(r)).toList();
  }

  // --- watchlist ---
  Future<void> addWatchlist(WatchlistItem item) async {
    final db = await database;
    await db.insert('watchlist', item.toMap(), conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<void> removeWatchlist(String code) async {
    final db = await database;
    await db.delete('watchlist', where: 'code = ?', whereArgs: [code]);
  }

  Future<List<WatchlistItem>> getWatchlist() async {
    final db = await database;
    final rows = await db.query('watchlist', orderBy: 'created_at DESC');
    return rows.map((r) => WatchlistItem.fromMap(r)).toList();
  }

  Future<bool> isInWatchlist(String code) async {
    final db = await database;
    final rows = await db.query('watchlist', where: 'code = ?', whereArgs: [code], limit: 1);
    return rows.isNotEmpty;
  }

  // --- sync_tasks ---
  Future<Map<String, dynamic>?> getSyncTask(String taskId) async {
    final db = await database;
    final rows = await db.query('sync_tasks', where: 'task_id = ?', whereArgs: [taskId], limit: 1);
    return rows.isEmpty ? null : rows.first;
  }

  Future<void> upsertSyncTask(String taskId, String status, {String? sources, String? message, String? error}) async {
    final db = await database;
    final now = DateTime.now().toIso8601String();
    await db.insert('sync_tasks', {
      'task_id': taskId,
      'status': status,
      'sources': sources,
      'message': message,
      'error': error,
      'created_at': now,
      'updated_at': now,
    }, conflictAlgorithm: ConflictAlgorithm.replace);
  }
}
