import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../config/theme.dart';
import '../providers/watchlist_provider.dart';
import 'etf_detail_screen.dart';

class WatchlistScreen extends StatelessWidget {
  const WatchlistScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<WatchlistProvider>();
    final isDark = Theme.of(context).brightness == Brightness.dark;

    if (provider.items.isEmpty) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.star_border, size: 64, color: Colors.grey),
            SizedBox(height: 16),
            Text('暂无自选股', style: TextStyle(color: Colors.grey)),
            Text('在ETF列表中长按添加', style: TextStyle(color: Colors.grey, fontSize: 12)),
          ],
        ),
      );
    }

    return ListView.builder(
      itemCount: provider.items.length,
      itemBuilder: (context, index) {
        final item = provider.items[index];
        return Dismissible(
          key: Key(item.code),
          direction: DismissDirection.endToStart,
          background: Container(
            alignment: Alignment.centerRight,
            padding: const EdgeInsets.only(right: 16),
            color: Colors.red,
            child: const Icon(Icons.delete, color: Colors.white),
          ),
          onDismissed: (_) => provider.remove(item.code),
          child: Card(
            margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
            color: isDark ? AppColors.darkSurface : AppColors.lightSurface,
            child: ListTile(
              title: Text(item.code, style: const TextStyle(fontSize: 14)),
              subtitle: Text(item.type.toUpperCase(), style: const TextStyle(fontSize: 12)),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => Navigator.push(
                context,
                MaterialPageRoute(builder: (_) => EtfDetailScreen(code: item.code, name: item.code)),
              ),
            ),
          ),
        );
      },
    );
  }
}
