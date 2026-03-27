WITH paid_orders AS (
  SELECT
    o.order_id,
    o.user_id,
    o.region,
    o.order_date,
    o.paid_at
  FROM fact_orders o
  WHERE o.order_status = 'PAID'
    AND o.order_date >= DATE '2025-01-01'
    AND o.order_date < DATE '2025-04-01'
),
order_gmv AS (
  SELECT
    po.order_id,
    po.user_id,
    po.region,
    po.order_date,
    SUM(od.quantity * od.unit_price) AS order_amount,
    SUM(CASE WHEN p.category = 'Electronics' THEN od.quantity * od.unit_price ELSE 0 END) AS electronics_amount,
    COUNT(DISTINCT od.product_id) AS sku_count
  FROM paid_orders po
  JOIN fact_order_items od ON po.order_id = od.order_id
  LEFT JOIN dim_products p ON od.product_id = p.product_id
  GROUP BY po.order_id, po.user_id, po.region, po.order_date
)
SELECT
  og.region,
  DATE_TRUNC('month', og.order_date) AS order_month,
  COUNT(DISTINCT og.order_id) AS paid_order_cnt,
  COUNT(DISTINCT og.user_id) AS buyer_cnt,
  SUM(og.order_amount) AS gmv,
  AVG(og.order_amount) AS avg_order_amount,
  SUM(og.electronics_amount) AS electronics_gmv,
  SUM(og.electronics_amount) / NULLIF(SUM(og.order_amount), 0) AS electronics_share,
  RANK() OVER (
    PARTITION BY DATE_TRUNC('month', og.order_date)
    ORDER BY SUM(og.order_amount) DESC
  ) AS region_rank_in_month
FROM order_gmv og
GROUP BY og.region, DATE_TRUNC('month', og.order_date)
HAVING COUNT(DISTINCT og.order_id) >= 20
ORDER BY order_month, gmv DESC;
