import 'package:flutter/material.dart';
import 'package:flutter_staggered_animations/flutter_staggered_animations.dart';
import 'package:shimmer/shimmer.dart';
import 'package:google_fonts/google_fonts.dart';
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
        _buildSearchBar(provider, isDark),
        _buildFilterChips(provider, isDark),
        _buildSortHeader(provider, isDark),
        Expanded(
          child: provider.bars.isEmpty
              ? _buildLoadingShimmer(isDark)
              : AnimationLimiter(
                  child: ListView.builder(
                    itemCount: provider.bars.length,
                    itemBuilder: (context, index) {
                      return AnimationConfiguration.staggeredList(
                        position: index,
                        duration: const Duration(milliseconds: 375),
                        child: SlideAnimation(
                          verticalOffset: 50.0,
                          child: FadeInAnimation(
                            child: _buildEtfCard(provider.bars[index], provider, isDark),
                          ),
                        ),
                      );
                    },
                  ),
                ),
        ),
      ],
    );
  }

  Widget _buildSearchBar(EtfProvider provider, bool isDark) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
      child: TextField(
        controller: _searchController,
        style: GoogleFonts.notoSansSc(fontSize: 14),
        decoration: InputDecoration(
          hintText: '搜索 ETF 代码或名称...',
          hintStyle: TextStyle(color: isDark ? AppColors.darkTextSecondary : AppColors.lightTextSecondary),
          prefixIcon: Icon(Icons.search, color: isDark ? AppColors.darkTextSecondary : AppColors.lightTextSecondary),
          suffixIcon: _searchController.text.isNotEmpty
              ? IconButton(
                  icon: const Icon(Icons.clear, size: 18),
                  onPressed: () {
                    _searchController.clear();
                    provider.setSearch('');
                  },
                )
              : null,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: BorderSide.none,
          ),
          filled: true,
          fillColor: isDark ? AppColors.darkSurface : AppColors.lightSurface,
          contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        ),
        onChanged: (v) => provider.setSearch(v),
      ),
    );
  }

  Widget _buildFilterChips(EtfProvider provider, bool isDark) {
    return SizedBox(
      height: 44,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12),
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
        label: Text(
          label,
          style: TextStyle(
            fontSize: 12,
            fontWeight: selected ? FontWeight.w600 : FontWeight.normal,
            color: selected ? Colors.white : (isDark ? AppColors.darkTextPrimary : AppColors.lightTextPrimary),
          ),
        ),
        selected: selected,
        onSelected: (_) => onTap(value),
        selectedColor: AppColors.darkAccent,
        backgroundColor: isDark ? AppColors.darkSurface : AppColors.lightSurface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        side: BorderSide(
          color: selected ? AppColors.darkAccent : (isDark ? AppColors.darkSurface : Colors.grey.shade300),
        ),
      ),
    );
  }

  Widget _buildSortHeader(EtfProvider provider, bool isDark) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: isDark ? AppColors.darkSurface : AppColors.lightSurface,
        border: Border(
          bottom: BorderSide(color: isDark ? Colors.white10 : Colors.grey.shade200),
        ),
      ),
      child: Row(
        children: [
          Expanded(flex: 3, child: _sortButton('代码/名称', 'code', provider)),
          Expanded(flex: 2, child: _sortButton('现价', 'close', provider, align: TextAlign.right)),
          Expanded(flex: 2, child: _sortButton('涨跌%', 'chg_pct', provider, align: TextAlign.right)),
          Expanded(flex: 2, child: _sortButton('RPS10', 'rps_10', provider, align: TextAlign.right)),
          Expanded(flex: 2, child: _sortButton('RPS50', 'rps_50', provider, align: TextAlign.right)),
          Expanded(flex: 2, child: _sortButton('RPS120', 'rps_120', provider, align: TextAlign.right)),
        ],
      ),
    );
  }

  Widget _sortButton(String label, String field, EtfProvider provider, {TextAlign align = TextAlign.left}) {
    final isActive = provider.sortField == field;
    return GestureDetector(
      onTap: () => provider.setSort(field),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        mainAxisAlignment: align == TextAlign.right ? MainAxisAlignment.end : MainAxisAlignment.start,
        children: [
          Text(
            label,
            style: TextStyle(
              fontSize: 11,
              fontWeight: isActive ? FontWeight.bold : FontWeight.normal,
              color: isActive ? AppColors.darkAccent : null,
            ),
          ),
          if (isActive)
            Icon(
              provider.sortAscending ? Icons.arrow_upward : Icons.arrow_downward,
              size: 12,
              color: AppColors.darkAccent,
            ),
        ],
      ),
    );
  }

  Widget _buildEtfCard(dynamic bar, EtfProvider provider, bool isDark) {
    final name = provider.getName(bar.stockCode);
    final chgColor = (bar.chgPct ?? 0) > 0
        ? AppColors.rise
        : (bar.chgPct ?? 0) < 0
            ? AppColors.fall
            : AppColors.flat;

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 3),
      color: isDark ? AppColors.darkSurface : AppColors.lightSurface,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      elevation: 1,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => Navigator.push(
          context,
          PageRouteBuilder(
            pageBuilder: (_, __, ___) => EtfDetailScreen(code: bar.stockCode, name: name),
            transitionsBuilder: (_, animation, __, child) {
              return FadeTransition(opacity: animation, child: child);
            },
          ),
        ),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          child: Row(
            children: [
              Expanded(
                flex: 3,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      bar.stockCode,
                      style: GoogleFonts.notoSansSc(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: isDark ? AppColors.darkTextPrimary : AppColors.lightTextPrimary,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      name,
                      style: TextStyle(
                        fontSize: 11,
                        color: isDark ? AppColors.darkTextSecondary : AppColors.lightTextSecondary,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
              Expanded(
                flex: 2,
                child: Text(
                  bar.close?.toStringAsFixed(3) ?? '-',
                  textAlign: TextAlign.right,
                  style: GoogleFonts.notoSansSc(
                    fontSize: 13,
                    fontWeight: FontWeight.w500,
                    color: chgColor,
                  ),
                ),
              ),
              Expanded(
                flex: 2,
                child: Container(
                  margin: const EdgeInsets.only(left: 8),
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: chgColor.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    '${bar.chgPct != null ? (bar.chgPct! > 0 ? '+' : '') : ''}${bar.chgPct?.toStringAsFixed(2) ?? '-'}%',
                    textAlign: TextAlign.center,
                    style: GoogleFonts.notoSansSc(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: chgColor,
                    ),
                  ),
                ),
              ),
              Expanded(
                flex: 2,
                child: _rpsBadge('R10', bar.rps10, isDark),
              ),
              Expanded(
                flex: 2,
                child: _rpsBadge('R50', bar.rps50, isDark),
              ),
              Expanded(
                flex: 2,
                child: _rpsBadge('R120', bar.rps120, isDark),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _rpsBadge(String label, double? value, bool isDark) {
    final v = value ?? 0;
    final color = v > 87
        ? AppColors.rise
        : v > 50
            ? AppColors.darkAccent
            : (isDark ? AppColors.darkTextSecondary : AppColors.lightTextSecondary);
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(label, style: TextStyle(fontSize: 9, color: color, fontWeight: FontWeight.w500)),
        const SizedBox(height: 1),
        Text(
          v.toStringAsFixed(1),
          style: TextStyle(fontSize: 11, color: color, fontWeight: FontWeight.bold),
        ),
      ],
    );
  }

  Widget _buildLoadingShimmer(bool isDark) {
    return Shimmer.fromColors(
      baseColor: isDark ? AppColors.darkSurface : Colors.grey.shade300,
      highlightColor: isDark ? Colors.white12 : Colors.grey.shade100,
      child: ListView.builder(
        itemCount: 8,
        padding: const EdgeInsets.all(12),
        itemBuilder: (_, __) => Container(
          height: 60,
          margin: const EdgeInsets.only(bottom: 8),
          decoration: BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.circular(12),
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }
}
