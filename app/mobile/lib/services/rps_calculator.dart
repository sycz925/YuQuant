class RpsCalculator {
  static double calculateRps(List<double> allReturns, double targetReturn) {
    if (allReturns.isEmpty) return 0;
    int rank = 0;
    for (final r in allReturns) {
      if (r <= targetReturn) rank++;
    }
    return (rank / allReturns.length) * 100;
  }

  static Map<String, double> calculateAllRps({
    required List<Map<String, dynamic>> bars,
    required int period,
  }) {
    final returns = <String, double>{};
    final allReturns = <double>[];

    for (final bar in bars) {
      final code = bar['stock_code'] as String;
      final change = bar['chg_${period}d'] as double?;
      if (change != null) {
        returns[code] = change;
        allReturns.add(change);
      }
    }

    final rps = <String, double>{};
    for (final entry in returns.entries) {
      rps[entry.key] = calculateRps(allReturns, entry.value);
    }
    return rps;
  }

  static bool isThreeLineRed(Map<String, dynamic> etf) {
    final rps10 = etf['rps_10'] as double? ?? 0;
    final rps50 = etf['rps_50'] as double? ?? 0;
    final rps120 = etf['rps_120'] as double? ?? 0;
    return rps10 > 87 && rps50 > 87 && rps120 > 87;
  }

  static int redLineCount(Map<String, dynamic> etf) {
    int count = 0;
    if ((etf['rps_10'] as double? ?? 0) > 87) count++;
    if ((etf['rps_50'] as double? ?? 0) > 87) count++;
    if ((etf['rps_120'] as double? ?? 0) > 87) count++;
    return count;
  }

  static List<double?> calculateMa(List<double> prices, int period) {
    final result = <double?>[];
    for (int i = 0; i < prices.length; i++) {
      if (i < period - 1) {
        result.add(null);
      } else {
        double sum = 0;
        for (int j = i - period + 1; j <= i; j++) {
          sum += prices[j];
        }
        result.add(double.parse((sum / period).toStringAsFixed(3)));
      }
    }
    return result;
  }

  static List<double?> calculateVolMa(List<int> volumes, int period) {
    final result = <double?>[];
    for (int i = 0; i < volumes.length; i++) {
      if (i < period - 1) {
        result.add(null);
      } else {
        double sum = 0;
        for (int j = i - period + 1; j <= i; j++) {
          sum += volumes[j];
        }
        result.add(double.parse((sum / period).toStringAsFixed(2)));
      }
    }
    return result;
  }

  static double? calculateChgPeriod(double? currentClose, double? periodClose) {
    if (currentClose == null || periodClose == null || periodClose == 0) return null;
    return ((currentClose - periodClose) / periodClose * 100);
  }
}
