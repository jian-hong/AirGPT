-- certified query cq_sales_top5_value (AirGPT hybrid_max / free route)
SELECT sku, ROUND(SUM(sales_value_myr), 2) AS sales_value_myr
FROM Sales
WHERE sku NOT IN ('SKU-00397')
GROUP BY sku
ORDER BY sales_value_myr DESC
LIMIT 5;