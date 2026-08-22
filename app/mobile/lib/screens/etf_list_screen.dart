import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../config/theme.dart';
import '../providers/etf_provider.dart';
import 'etf_detail_screen.dart';

class EtfListScreen extends StatefulWidget {
  const EtfListScreen({super.key});

  @override
  State<EtfListScreen> createState() => _EtfListScreenState();
}

class _EtfListScreenState extends State<EtfListScreen> {
  final _searchController = TextEditingController();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<EtfProvider>().loadData();
    });
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<EtfProvider>();
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.all(8.0),
          child: TextField(
            controller: _searchController,
            decoration: InputDecoration(
              hintText: '搜索ETF...',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: _searchController.text.isNotEmpty
                  ? IconButton(
                      icon: const Icon(Icons.clear),
                      onPressed: () {
                        _searchController.clear();
                        provider.setSearch('');
                      },
                    )
                  : null,
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
              filled: true,
              fillColor: isDark ? AppColors.darkSurface : AppColors.lightSurface,
            ),
            onChanged: (v) => provider.setSearch(v),
          ),
        ),
        _buildFilterChips(provider, isDark),
        _buildSortHeader(provider, isDark),
        Expanded(
          child: provider.bars.isEmpty
              ? const Center(child: Text('暂无数据，请先同步'))
              : ListView.builder(
                  itemCount: provider.bars.length,
                  itemBuilder: (context, index) {
                    final bar = provider.bars[index];
                    final name = provider.getName(bar.stockCode);
                    return _buildEtfCard(bar, name, isDark);
                  },
                ),
        ),
      ],
    );
  }

  Widget _buildFilterChips(EtfProvider provider, bool isDark) {
    return SizedBox(
      height: 40,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 8),
        children: [
          _filterChip('全部', 0, provider.redFilter, (v) => provider.setRedFilter(v), isDark),
          _filterChip('三线红', 3, provider.redFilter, (v) => provider.setRedFilter(v), isDark),
          _filterChip('二线红', 2, provider.redFilter, (v) => provider.setRedFilter(v), isDark),
          _filterChip('一线红', 1, provider.redFilter, (v) => provider.setRedFilter(v), isDark),
        ],
      ),
    );
  }

  Widget _filterChip(String label, int value, int current, Function(int) onTap, bool isDark) {
    final selected = value == current;
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: FilterChip(
        label: Text(label, style: TextStyle(fontSize: 12, color: selected ? Colors.white : null)),
        selected: selected,
        onSelected: (_) => onTap(value),
        selectedColor: AppColors.darkAccent,
        backgroundColor: isDark ? AppColors.darkSurface : AppColors.lightSurface,
      ),
    );
  }

  Widget _buildSortHeader(EtfProvider provider, bool isDark) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      color: isDark ? AppColors.darkSurface : AppColors.lightSurface,
      child: Row(
        children: [
          Expanded(flex: 2, child: _sortButton('代码', 'code', provider)),
          Expanded(flex: 2, child: _sortButton('名称', 'code', provider)),
          Expanded(child: _sortButton('现价', 'close', provider)),
          Expanded(child: _sortButton('涨跌%', 'chg_pct', provider)),
          Expanded(child: _sortButton('RPS10', 'rps_10', provider)),
          Expanded(child: _sortButton('RPS50', 'rps_50', provider)),
          Expanded(child: _sortButton('RPS120', 'rps_120', provider)),
        ],
      ),
    );
  }

  Widget _sortButton(String label, String field, EtfProvider provider) {
    final isActive = provider.sortField == field;
    return GestureDetector(
      onTap: () => provider.setSort(field),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(label, style: TextStyle(fontSize: 11, fontWeight: isActive ? FontWeight.bold : null)),
          if (isActive)
            Icon(
              provider.sortAscending ? Icons.arrow_upward : Icons.arrow_downward,
              size: 12,
            ),
        ],
      ),
    );
  }

  Widget _buildEtfCard(dynamic bar, String name, bool isDark) {
    final chgColor = (bar.chgPct ?? 0) > 0
        ? AppColors.rise
        : (bar.chgPct ?? 0) < 0
            ? AppColors.fall
            : AppColors.flat;

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      color: isDark ? AppColors.darkSurface : AppColors.lightSurface,
      child: ListTile(
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => EtfDetailScreen(code: bar.stockCode, name: name)),
        ),
        title: Text('${bar.stockCode} $name', style: const TextStyle(fontSize: 14)),
        subtitle: Row(
          children: [
            Text('${bar.close?.toStringAsFixed(3) ?? '-'}', style: TextStyle(color: chgColor, fontSize: 12)),
            const SizedBox(width: 8),
            Text('${bar.chgPct?.toStringAsFixed(2) ?? '-'}%', style: TextStyle(color: chgColor, fontSize: 12)),
          ],
        ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            _rpsBadge('R10', bar.rps10, isDark),
            const SizedBox(width: 4),
            _rpsBadge('R50', bar.rps50, isDark),
            const SizedBox(width: 4),
            _rpsBadge('R120', bar.rps120, isDark),
          ],
        ),
      ),
    );
  }

  Widget _rpsBadge(String label, double? value, bool isDark) {
    final v = value ?? 0;
    final color = v > 87 ? AppColors.rise : (isDark ? AppColors.darkTextSecondary : AppColors.lightTextSecondary);
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(label, style: TextStyle(fontSize: 9, color: color)),
        Text(v.toStringAsFixed(1), style: TextStyle(fontSize: 10, color: color, fontWeight: FontWeight.bold)),
      ],
    );
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }
}
